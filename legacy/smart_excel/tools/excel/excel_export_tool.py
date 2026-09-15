import io
import logging
import os
import sqlite3
# import xlsxwriter # 移除 xlsxwriter
import csv

# 重新导入 pandas 和 openpyxl
import pandas as pd
import openpyxl # pandas 的 ExcelWriter 需要它作为引擎来处理 .xlsx 文件

from db_server.config.db_config import Config

# 每个工作表的最大数据行数 (不包括表头)
# 用户指定每100万一个sheet，这里指数据行
DEFAULT_MAX_DATA_ROWS_PER_SHEET = 1000000
# 创建 DataFrame 并写入 Excel 时，每个 DataFrame 块的最大行数
DATAFRAME_WRITE_CHUNK_SIZE = 200000 # "二十万一次"

class SqliteToExportExcel:

    @staticmethod
    def export_from_sqlite_to_excel_stream(db_path: str, table_name: str,
                                           chunk_size_export=50000): # "五万一次" (从数据库读取)
        """
        使用 pandas 和 openpyxl 将 SQLite 数据逐块写入 Excel 文件流。
        数据以 DATAFRAME_WRITE_CHUNK_SIZE 行的块创建DataFrame并写入工作表。
        每个工作表最多 DEFAULT_MAX_DATA_ROWS_PER_SHEET 行。

        :param db_path: SQLite 数据库文件路径
        :param table_name: 要导出的表名
        :param chunk_size_export: 从数据库读取数据时每个块的大小
        :return: (bool, str, io.BytesIO or None) - (成功标志, 消息, Excel流)
        """
        conn = None
        excel_stream = io.BytesIO()
        try:
            sqlite_file_path = db_path[10:] if db_path.startswith('sqlite:///') else db_path
            if not os.path.exists(sqlite_file_path):
                error_msg = f"数据库文件未找到: {sqlite_file_path}"
                logging.error(error_msg)
                return False, error_msg, None

            logging.info(
                f"开始从SQLite数据库 {sqlite_file_path} 的表 {table_name} 导出数据到流 (pandas/openpyxl, "
                f"DB分块大小: {chunk_size_export}, DF写入分块大小: {DATAFRAME_WRITE_CHUNK_SIZE})"
            )
            conn = sqlite3.connect(sqlite_file_path)
            cursor = conn.cursor()

            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
            if cursor.fetchone() is None:
                conn.close()
                error_msg = f"表 '{table_name}' 在数据库 '{sqlite_file_path}' 中不存在。"
                logging.error(error_msg)
                return False, error_msg, None

            cursor.execute(f"PRAGMA table_info('{table_name}')")
            headers = [row[1] for row in cursor.fetchall()]
            if not headers:
                conn.close()
                error_msg = f"无法获取表 '{table_name}' 的列信息。"
                logging.error(error_msg)
                return False, error_msg, None

            with pd.ExcelWriter(excel_stream, engine='openpyxl') as writer:
                total_rows_exported_overall = 0
                sheet_count = 0
                
                base_sheet_name = table_name
                if len(base_sheet_name) > 20:
                    base_sheet_name = base_sheet_name[:20]

                columns_expression = ', '.join(f'"{h}"' for h in headers)
                query = f"SELECT {columns_expression} FROM '{table_name}'"
                cursor.execute(query)

                rows_buffer_for_df_chunks = []
                
                current_sheet_name = ""
                rows_written_to_current_sheet = 0
                first_write_to_current_sheet = True
                db_has_more_data = True

                while db_has_more_data or rows_buffer_for_df_chunks:
                    # 1. 填充数据缓冲区直到达到 DATAFRAME_WRITE_CHUNK_SIZE 或数据库耗尽
                    while db_has_more_data and len(rows_buffer_for_df_chunks) < DATAFRAME_WRITE_CHUNK_SIZE:
                        rows_from_db = cursor.fetchmany(chunk_size_export)
                        if not rows_from_db:
                            db_has_more_data = False
                            break # 退出内部填充循环
                        else:
                            rows_buffer_for_df_chunks.extend(rows_from_db)
                            logging.info(
                                f"从数据库获取 {len(rows_from_db)} 行, 缓冲区现有 {len(rows_buffer_for_df_chunks)} 行 (流导出)"
                            )
                    
                    if not rows_buffer_for_df_chunks: # 如果缓冲区在填充尝试后仍为空，则表示已无数据可处理
                        break

                    # 2. 检查是否需要开始新工作表
                    if not current_sheet_name or rows_written_to_current_sheet >= DEFAULT_MAX_DATA_ROWS_PER_SHEET:
                        if current_sheet_name and rows_written_to_current_sheet > 0:
                            logging.info(
                                f"工作表 {current_sheet_name} 完成, 共 {rows_written_to_current_sheet} 行 (流导出)."
                            )
                        sheet_count += 1
                        current_sheet_name = f"{base_sheet_name}_part{sheet_count}"
                        rows_written_to_current_sheet = 0
                        first_write_to_current_sheet = True
                        logging.info(f"开始新工作表: {current_sheet_name} (流导出)")

                    # 3. 准备并写入一个DataFrame块
                    # 从缓冲区中取出用于当前DataFrame的数据量
                    rows_to_consider_from_buffer = min(len(rows_buffer_for_df_chunks), DATAFRAME_WRITE_CHUNK_SIZE)
                    
                    rows_for_this_df_payload = min(
                        rows_to_consider_from_buffer,
                        DEFAULT_MAX_DATA_ROWS_PER_SHEET - rows_written_to_current_sheet
                    )

                    if rows_for_this_df_payload == 0:
                        # 如果没有数据可形成有效载荷 (例如，当前工作表已满，但缓冲区仍有数据)
                        # 继续循环，将在下一次迭代开始时创建新工作表
                        logging.info(
                            f"计算得到的有效载荷为0。当前工作表可能已满 ({rows_written_to_current_sheet}/{DEFAULT_MAX_DATA_ROWS_PER_SHEET})。"
                            f"缓冲区大小: {len(rows_buffer_for_df_chunks)}。循环以处理新工作表或状态更新。"
                        )
                        continue 

                    data_for_df = rows_buffer_for_df_chunks[:rows_for_this_df_payload]
                    df_chunk = pd.DataFrame(data_for_df, columns=headers)

                    if first_write_to_current_sheet:
                        df_chunk.to_excel(writer, sheet_name=current_sheet_name, index=False, header=True)
                        first_write_to_current_sheet = False
                    else:
                        # startrow 是0索引的，表头在第0行，所以数据追加从 (已写数据行数 + 1) 开始
                        df_chunk.to_excel(writer, sheet_name=current_sheet_name, index=False, header=False,
                                          startrow=rows_written_to_current_sheet + 1)
                    
                    logging.info(
                        f"写入 {len(data_for_df)} 行到工作表 {current_sheet_name} "
                        f"(DF大小: {len(data_for_df)}, 此工作表累计: {rows_written_to_current_sheet + len(data_for_df)}) (流导出)"
                    )

                    rows_written_to_current_sheet += len(data_for_df)
                    total_rows_exported_overall += len(data_for_df)
                    rows_buffer_for_df_chunks = rows_buffer_for_df_chunks[rows_for_this_df_payload:]
                
                # 循环结束后，记录最后一个工作表的完成情况
                if current_sheet_name and rows_written_to_current_sheet > 0:
                    logging.info(
                        f"工作表 {current_sheet_name} 完成, 共 {rows_written_to_current_sheet} 行 (流导出)."
                    )

                # 处理完全空表的情况
                if total_rows_exported_overall == 0 and headers:
                    sheet_name_for_empty = base_sheet_name if base_sheet_name else "Sheet1"
                    df_empty = pd.DataFrame(columns=headers)
                    df_empty.to_excel(writer, sheet_name=sheet_name_for_empty, index=False, header=True)
                    logging.info(f"表 '{table_name}' 为空，已创建包含表头的工作表: {sheet_name_for_empty} (流导出)")
                
                logging.info(f"所有数据已提交给ExcelWriter，开始最终文件构建到内存流 (流导出)...")
            # 当 'with' 块结束时，writer.close() 会被调用，执行实际的文件生成和压缩，这可能很耗时

            logging.info("Excel文件流构建完成，重置流读取位置到开头 (pandas/openpyxl)")
            excel_stream.seek(0)
            logging.info("Excel文件流已准备好，关闭数据库连接 (pandas/openpyxl)")
            conn.close()
            logging.info("数据库连接已关闭 (pandas/openpyxl)")
            success_msg = (
                f"数据已成功从表 {table_name} 导出到Excel文件流 (pandas/openpyxl)，共 {total_rows_exported_overall} 行数据"
                f"{f'，分布在 {sheet_count} 个工作表中。' if sheet_count > 0 else '。'}"
            )
            logging.info(success_msg)
            return True, success_msg, excel_stream

        except Exception as e:
            error_msg = f"导出数据到Excel文件流时发生错误 (pandas/openpyxl): {e}"
            logging.error(error_msg, exc_info=True)
            if conn:
                conn.close()
            if excel_stream: 
                excel_stream.close()
            return False, error_msg, None

    @staticmethod
    def export_from_sqlite_to_excel_file(db_path: str, table_name: str,
                                         output_file_path: str,
                                         chunk_size_export=50000, # "五万一次" (从数据库读取)
                                         max_data_rows_per_sheet=DEFAULT_MAX_DATA_ROWS_PER_SHEET):
        """
        将 SQLite 数据库中指定表的数据直接导出到 Excel 文件 (使用 pandas 和 openpyxl)。
        数据以 DATAFRAME_WRITE_CHUNK_SIZE 行的块创建DataFrame并写入工作表。
        每个工作表最多 max_data_rows_per_sheet 行。

        :param db_path: SQLite 数据库文件路径
        :param table_name: 要导出的表名
        :param output_file_path: 目标 Excel 文件路径
        :param chunk_size_export: 从数据库读取数据时每个块的大小
        :param max_data_rows_per_sheet: 每个工作表的最大数据行数 (不包括表头)
        :return: (bool, str) - (成功标志, 消息)
        """
        conn = None
        try:
            output_dir = os.path.dirname(output_file_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            sqlite_file_path = db_path[10:] if db_path.startswith('sqlite:///') else db_path
            if not os.path.exists(sqlite_file_path):
                error_msg = f"数据库文件未找到: {sqlite_file_path}"
                logging.error(error_msg)
                return False, error_msg

            logging.info(
                f"开始从SQLite数据库 {sqlite_file_path} 的表 {table_name} 导出数据到文件 {output_file_path} "
                f"(pandas/openpyxl, DB分块大小: {chunk_size_export}, DF写入分块大小: {DATAFRAME_WRITE_CHUNK_SIZE}, "
                f"每工作表最大数据行数: {max_data_rows_per_sheet})"
            )
            conn = sqlite3.connect(sqlite_file_path)
            cursor = conn.cursor()

            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
            if cursor.fetchone() is None:
                conn.close()
                error_msg = f"表 '{table_name}' 在数据库 '{sqlite_file_path}' 中不存在。"
                logging.error(error_msg)
                return False, error_msg
            
            cursor.execute(f"PRAGMA table_info('{table_name}')")
            headers = [row[1] for row in cursor.fetchall()]
            if not headers:
                conn.close()
                error_msg = f"无法获取表 '{table_name}' 的列信息。"
                logging.error(error_msg)
                return False, error_msg

            with pd.ExcelWriter(output_file_path, engine='openpyxl') as writer:
                total_rows_exported_overall = 0
                sheet_count = 0
                
                base_sheet_name = table_name
                if len(base_sheet_name) > 20: 
                    base_sheet_name = base_sheet_name[:20]

                columns_expression = ', '.join(f'"{h}"' for h in headers)
                query = f"SELECT {columns_expression} FROM '{table_name}'"
                cursor.execute(query)

                rows_buffer_for_df_chunks = []
                
                current_sheet_name = ""
                rows_written_to_current_sheet = 0
                first_write_to_current_sheet = True
                db_has_more_data = True

                while db_has_more_data or rows_buffer_for_df_chunks:
                    # 1. 填充数据缓冲区直到达到 DATAFRAME_WRITE_CHUNK_SIZE 或数据库耗尽
                    while db_has_more_data and len(rows_buffer_for_df_chunks) < DATAFRAME_WRITE_CHUNK_SIZE:
                        rows_from_db = cursor.fetchmany(chunk_size_export)
                        if not rows_from_db:
                            db_has_more_data = False
                            break # 退出内部填充循环
                        else:
                            rows_buffer_for_df_chunks.extend(rows_from_db)
                            logging.info(
                                f"从数据库获取 {len(rows_from_db)} 行, 缓冲区现有 {len(rows_buffer_for_df_chunks)} 行 (文件导出)"
                            )

                    if not rows_buffer_for_df_chunks: # 如果缓冲区在填充尝试后仍为空，则表示已无数据可处理
                        break
                    
                    # 2. 检查是否需要开始新工作表
                    if not current_sheet_name or rows_written_to_current_sheet >= max_data_rows_per_sheet:
                        if current_sheet_name and rows_written_to_current_sheet > 0:
                             logging.info(
                                f"工作表 {current_sheet_name} 完成, 共 {rows_written_to_current_sheet} 行 (文件导出)."
                            )
                        sheet_count += 1
                        current_sheet_name = f"{base_sheet_name}_part{sheet_count}"
                        rows_written_to_current_sheet = 0
                        first_write_to_current_sheet = True
                        logging.info(f"开始新工作表: {current_sheet_name} (文件导出)")

                    # 3. 准备并写入一个DataFrame块
                    # 从缓冲区中取出用于当前DataFrame的数据量
                    rows_to_consider_from_buffer = min(len(rows_buffer_for_df_chunks), DATAFRAME_WRITE_CHUNK_SIZE)

                    rows_for_this_df_payload = min(
                        rows_to_consider_from_buffer,
                        max_data_rows_per_sheet - rows_written_to_current_sheet
                    )

                    if rows_for_this_df_payload == 0:
                        # 如果没有数据可形成有效载荷 (例如，当前工作表已满，但缓冲区仍有数据)
                        # 继续循环，将在下一次迭代开始时创建新工作表
                        logging.info(
                            f"计算得到的有效载荷为0。当前工作表可能已满 ({rows_written_to_current_sheet}/{max_data_rows_per_sheet})。"
                            f"缓冲区大小: {len(rows_buffer_for_df_chunks)}。循环以处理新工作表或状态更新。"
                        )
                        continue

                    data_for_df = rows_buffer_for_df_chunks[:rows_for_this_df_payload]
                    df_chunk = pd.DataFrame(data_for_df, columns=headers)

                    if first_write_to_current_sheet:
                        df_chunk.to_excel(writer, sheet_name=current_sheet_name, index=False, header=True)
                        first_write_to_current_sheet = False
                    else:
                        df_chunk.to_excel(writer, sheet_name=current_sheet_name, index=False, header=False,
                                          startrow=rows_written_to_current_sheet + 1)
                    
                    logging.info(
                        f"写入 {len(data_for_df)} 行到工作表 {current_sheet_name} "
                        f"(DF大小: {len(data_for_df)}, 此工作表累计: {rows_written_to_current_sheet + len(data_for_df)}) (文件导出)"
                    )
                    
                    rows_written_to_current_sheet += len(data_for_df)
                    total_rows_exported_overall += len(data_for_df)
                    rows_buffer_for_df_chunks = rows_buffer_for_df_chunks[rows_for_this_df_payload:]

                if current_sheet_name and rows_written_to_current_sheet > 0:
                    logging.info(
                        f"工作表 {current_sheet_name} 完成, 共 {rows_written_to_current_sheet} 行 (文件导出)."
                    )

                if total_rows_exported_overall == 0 and headers:
                    sheet_name_for_empty = base_sheet_name if base_sheet_name else "Sheet1"
                    df_empty = pd.DataFrame(columns=headers)
                    df_empty.to_excel(writer, sheet_name=sheet_name_for_empty, index=False, header=True)
                    logging.info(f"表 '{table_name}' 为空，已创建包含表头的工作表: {sheet_name_for_empty} (文件导出)")

                logging.info(f"所有数据已提交给ExcelWriter，开始最终文件构建到路径 {output_file_path} (文件导出)...")
            # 当 'with' 块结束时，writer.close() 会被调用，执行实际的文件生成和压缩

            logging.info(f"Excel文件 {output_file_path} 构建完成。")
            conn.close()
            success_msg = (
                f"数据已成功从表 {table_name} 导出到文件 {output_file_path} (pandas/openpyxl)，共 {total_rows_exported_overall} 行数据"
                f"{f'，分布在 {sheet_count} 个工作表中。' if sheet_count > 0 else '。'}"
            )
            logging.info(success_msg)
            return True, success_msg

        except Exception as e:
            error_msg = f"导出数据到Excel文件 {output_file_path} 时发生错误 (pandas/openpyxl): {e}"
            logging.error(error_msg, exc_info=True)
            if conn:
                conn.close()
            if os.path.exists(output_file_path):
                try:
                    os.remove(output_file_path)
                    logging.info(f"错误发生，已尝试删除部分写入的文件: {output_file_path}")
                except OSError as oe:
                    logging.error(f"错误发生后删除文件 {output_file_path} 失败: {oe}")
            return False, error_msg

    @staticmethod
    def export_from_sqlite_to_csv_stream(db_path: str, table_name: str,
                                         chunk_size_export=50000, encoding='utf-8'):
        """
        将 SQLite 数据库中指定表的数据导出到 CSV 文件流。

        :param db_path: SQLite 数据库文件路径
        :param table_name: 要导出的表名
        :param chunk_size_export: 从数据库读取数据时每个块的大小
        :param encoding: CSV 文件流的编码
        :return: (bool, str, io.BytesIO or None) - (成功标志, 消息, CSV流)
        """
        conn = None
        csv_stream_bytes = None
        try:
            sqlite_file_path = db_path[10:] if db_path.startswith('sqlite:///') else db_path
            if not os.path.exists(sqlite_file_path):
                error_msg = f"数据库文件未找到: {sqlite_file_path}"
                logging.error(error_msg)
                return False, error_msg, None

            logging.info(
                f"开始从SQLite数据库 {sqlite_file_path} 的表 {table_name} 导出数据到CSV流 (分块大小: {chunk_size_export})"
            )
            conn = sqlite3.connect(sqlite_file_path)
            cursor = conn.cursor()

            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
            if cursor.fetchone() is None:
                conn.close()
                error_msg = f"表 '{table_name}' 在数据库 '{sqlite_file_path}' 中不存在。"
                logging.error(error_msg)
                return False, error_msg, None

            cursor.execute(f"PRAGMA table_info('{table_name}')")
            headers = [row[1] for row in cursor.fetchall()]
            if not headers:
                conn.close()
                error_msg = f"无法获取表 '{table_name}' 的列信息。"
                logging.error(error_msg)
                return False, error_msg, None

            # CSV写入器处理文本，所以先用StringIO，然后转为BytesIO
            string_io = io.StringIO(newline='') # newline='' 推荐用于csv写入
            csv_writer = csv.writer(string_io)

            csv_writer.writerow(headers)
            total_rows_exported = 0

            columns_expression = ', '.join(f'"{h}"' for h in headers)
            # 构建最终的 SQL 查询字符串
            query = f"SELECT {columns_expression} FROM '{table_name}'"
            cursor.execute(query)

            while True:
                rows_chunk = cursor.fetchmany(chunk_size_export)
                if not rows_chunk:
                    break
                
                csv_writer.writerows(rows_chunk)
                total_rows_exported += len(rows_chunk)
                logging.info(
                    f"已处理并写入 {len(rows_chunk)} 行数据到CSV流 (当前批次，总计已导出: {total_rows_exported})"
                )
            
            if total_rows_exported == 0:
                logging.info(f"表 '{table_name}' 为空，CSV流将只包含表头。")

            # 将StringIO的内容编码并放入BytesIO
            csv_stream_bytes = io.BytesIO(string_io.getvalue().encode(encoding))
            string_io.close() # 关闭StringIO
            csv_stream_bytes.seek(0)

            conn.close()
            success_msg = (
                f"数据已成功从表 {table_name} 导出到CSV文件流，共 {total_rows_exported} 行数据 (不含表头)。"
            )
            logging.info(success_msg)
            return True, success_msg, csv_stream_bytes

        except Exception as e:
            error_msg = f"导出数据到CSV文件流时发生错误: {e}"
            logging.error(error_msg, exc_info=True)
            if conn:
                conn.close()
            if csv_stream_bytes: # 虽然不太可能在这里创建，但以防万一
                csv_stream_bytes.close()
            return False, error_msg, None

    @staticmethod
    def export_from_sqlite_to_csv_file(db_path: str, table_name: str,
                                       output_file_path: str,
                                       chunk_size_export=50000, encoding='utf-8'):
        """
        将 SQLite 数据库中指定表的数据直接导出到 CSV 文件。

        :param db_path: SQLite 数据库文件路径
        :param table_name: 要导出的表名
        :param output_file_path: 目标 CSV 文件路径
        :param chunk_size_export: 从数据库读取数据时每个块的大小
        :param encoding: CSV 文件的编码
        :return: (bool, str) - (成功标志, 消息)
        """
        conn = None
        csv_file = None
        try:
            output_dir = os.path.dirname(output_file_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            sqlite_file_path = db_path[10:] if db_path.startswith('sqlite:///') else db_path
            if not os.path.exists(sqlite_file_path):
                error_msg = f"数据库文件未找到: {sqlite_file_path}"
                logging.error(error_msg)
                return False, error_msg

            logging.info(
                f"开始从SQLite数据库 {sqlite_file_path} 的表 {table_name} 导出数据到CSV文件 {output_file_path} "
                f"(分块大小: {chunk_size_export})")
            conn = sqlite3.connect(sqlite_file_path)
            cursor = conn.cursor()

            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
            if cursor.fetchone() is None:
                conn.close()
                error_msg = f"表 '{table_name}' 在数据库 '{sqlite_file_path}' 中不存在。"
                logging.error(error_msg)
                return False, error_msg
            
            cursor.execute(f"PRAGMA table_info('{table_name}')")
            headers = [row[1] for row in cursor.fetchall()]
            if not headers:
                conn.close()
                error_msg = f"无法获取表 '{table_name}' 的列信息。"
                logging.error(error_msg)
                return False, error_msg

            with open(output_file_path, 'w', newline='', encoding=encoding) as csv_file:
                csv_writer = csv.writer(csv_file)
                csv_writer.writerow(headers)
                total_rows_exported = 0

                columns_expression = ', '.join(f'"{h}"' for h in headers)
                # 构建最终的 SQL 查询字符串
                query = f"SELECT {columns_expression} FROM '{table_name}'"
                cursor.execute(query)

                while True:
                    rows_chunk = cursor.fetchmany(chunk_size_export)
                    if not rows_chunk:
                        break
                    
                    csv_writer.writerows(rows_chunk)
                    total_rows_exported += len(rows_chunk)
                    logging.info(
                        f"已处理并写入 {len(rows_chunk)} 行数据到CSV文件 (总计导出: {total_rows_exported})")
                
                if total_rows_exported == 0:
                    logging.info(f"表 '{table_name}' 为空，CSV文件将只包含表头。")

            conn.close()
            success_msg = (
                f"数据已成功从表 {table_name} 导出到CSV文件 {output_file_path}，共 {total_rows_exported} 行数据 (不含表头)。"
            )
            logging.info(success_msg)
            return True, success_msg

        except Exception as e:
            error_msg = f"导出数据到CSV文件 {output_file_path} 时发生错误: {e}"
            logging.error(error_msg, exc_info=True)
            if conn:
                conn.close()
            # 如果文件已创建且发生错误，可以考虑删除不完整的文件
            if os.path.exists(output_file_path):
                try:
                    # 仅当文件句柄未正确关闭或写入中途失败时考虑删除
                    # with open 会确保文件在退出时关闭，但如果写入中途异常，文件可能不完整
                    # 为简单起见，如果出错就尝试删除
                    os.remove(output_file_path)
                    logging.info(f"错误发生，已尝试删除部分写入的CSV文件: {output_file_path}")
                except OSError as oe:
                    logging.warning(f"错误发生后删除CSV文件 {output_file_path} 失败: {oe}")
            return False, error_msg


def export_table_to_excel_stream(task_id: str, table_name: str):
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    return SqliteToExportExcel.export_from_sqlite_to_excel_stream(db_path=db_path, table_name=table_name)

def export_table_to_excel_file_path(task_id: str, table_name: str, file_path: str):
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    return SqliteToExportExcel.export_from_sqlite_to_excel_file(db_path=db_path, table_name=table_name, output_file_path=file_path)

def export_table_to_csv_stream(task_id: str, table_name: str):
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    return SqliteToExportExcel.export_from_sqlite_to_csv_stream(db_path=db_path, table_name=table_name)

def export_table_to_csv_file_path(task_id: str, table_name: str, file_path: str):
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    return SqliteToExportExcel.export_from_sqlite_to_csv_file(db_path=db_path, table_name=table_name, output_file_path=file_path)
