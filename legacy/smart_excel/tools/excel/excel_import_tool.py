# -*- coding: utf-8 -*-
import io
import logging
import sqlite3
import os

import openpyxl
import pandas as pd
from openpyxl.cell.read_only import EmptyCell

from db_server.config.db_config import Config

class ImportExcelToSQLite:
    @staticmethod
    def do_import_to_sqlite(file_stream: io.BytesIO,
                            table_name: str,
                            db_path: str,
                            sheet_name_or_index=0,
                            chunk_size=50000):
        """
        优化版：使用pandas处理较小的Excel文件
        """
        conn = None
        try:
            # 处理数据库路径
            if db_path.startswith('sqlite:///'):
                sqlite_file_path = db_path[10:]
            else:
                sqlite_file_path = db_path

            # 确保目录存在
            dir_name = os.path.dirname(sqlite_file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            # 读取Excel文件
            file_stream.seek(0)
            excel_file = pd.ExcelFile(file_stream, engine='openpyxl')

            # 获取实际的工作表名
            if isinstance(sheet_name_or_index, int):
                if sheet_name_or_index >= len(excel_file.sheet_names):
                    excel_file.close()
                    return False, f"工作表索引 {sheet_name_or_index} 超出范围"
                sheet_name = excel_file.sheet_names[sheet_name_or_index]
            else:
                sheet_name = sheet_name_or_index
                if sheet_name not in excel_file.sheet_names:
                    excel_file.close()
                    return False, f"工作表 '{sheet_name}' 在Excel文件中未找到"

            sample_df = pd.read_excel(
                file_stream,
                sheet_name=sheet_name_or_index,
                nrows=1000,  # 读取前1000行作为样本
                engine='openpyxl'
            )

            # 处理列名，确保没有无名列
            sample_df.columns = [str(col) if col is not None else f"Unnamed_{i}"
                                 for i, col in enumerate(sample_df.columns)]

            # 根据样本数据推断列类型
            column_types = {}
            for col in sample_df.columns:
                # 尝试推断数值类型
                if pd.api.types.is_numeric_dtype(sample_df[col]):
                    if sample_df[col].dropna().apply(lambda x: float(x).is_integer()).all():
                        column_types[col] = 'INTEGER'
                    else:
                        column_types[col] = 'REAL'
                else:
                    column_types[col] = 'TEXT'

            # 根据推断的类型转换数据类型
            for col in sample_df.columns:
                if column_types[col] == 'INTEGER':
                    sample_df[col] = pd.to_numeric(sample_df[col], errors='coerce').fillna(0).astype('int64')
                elif column_types[col] == 'REAL':
                    sample_df[col] = pd.to_numeric(sample_df[col], errors='coerce').fillna(0).astype('float64')
                else:
                    # 处理文本类型，将None和NaN转为空字符串
                    sample_df[col] = sample_df[col].fillna('').astype(str)

            # 创建数据库连接
            conn = sqlite3.connect(sqlite_file_path, isolation_level=None, check_same_thread=False)

            # 创建表结构
            sample_df.to_sql(
                name=table_name,
                con=conn,
                if_exists='replace',
                index=False
            )

            # 分批读取和处理数据
            total_rows_imported = 1000  # 已导入1000行用于表结构
            nrows = chunk_size
            skiprows = 1000 + 1  # 跳过已处理的行和表头

            while True:
                chunk_df = pd.read_excel(
                    excel_file,
                    sheet_name=sheet_name,
                    skiprows=skiprows,
                    nrows=nrows,
                    header=None,
                    names=sample_df.columns,
                    engine='openpyxl'
                )

                if len(chunk_df) == 0:
                    break

                # 根据推断的类型转换数据类型
                for col in chunk_df.columns:
                    if column_types[col] == 'INTEGER':
                        chunk_df[col] = pd.to_numeric(chunk_df[col], errors='coerce')
                    elif column_types[col] == 'REAL':
                        chunk_df[col] = pd.to_numeric(chunk_df[col], errors='coerce')
                    else:
                        chunk_df[col] = chunk_df[col].astype(str)

                # 使用to_sql批量插入数据
                chunked_to_sql(
                    df=chunk_df,
                    table_name=table_name,
                    conn=conn,
                    if_exists='append'
                )

                rows_in_chunk = len(chunk_df)
                total_rows_imported += rows_in_chunk
                logging.info(f"已导入{rows_in_chunk}行数据 (总计: {total_rows_imported}行)")

                skiprows += nrows

                # 如果读取的行数少于请求的行数，说明已到文件末尾
                if rows_in_chunk < nrows:
                    break

            excel_file.close()
            conn.close()

            success_msg = f"数据已成功导入到表 {table_name} 中，共 {total_rows_imported} 行。"
            logging.info(success_msg)
            return True, success_msg

        except Exception as e:
            error_msg = f"从文件流导入数据时发生错误: {e}"
            logging.error(error_msg, exc_info=True)
            if 'conn' in locals() and conn:
                conn.close()
            return False, error_msg


    @staticmethod
    def do_import_to_sqlite_with_merged_cell(file_stream: io.BytesIO,
                            table_name: str,
                            db_path: str,
                            sheet_name_or_index=0,
                            chunk_size=50000,
                            sample_rows_for_type_inference=1000):
        """
        一次性读取 Excel 文件流并批量插入数据库。
        优化版：支持大型文件，通过流式处理和分块插入，并正确处理合并单元格。

        :param file_stream: Excel文件的内存流对象 (例如 io.BytesIO)
        :param table_name: 目标表名
        :param db_path: 数据库路径
        :param sheet_name_or_index: 工作表名称(str)或索引(int)，默认为0（第一个工作表）
        :param chunk_size: 每批插入数据库的行数
        :param sample_rows_for_type_inference: 用于推断列类型的样本行数
        """
        conn = None
        try:
            if db_path.startswith('sqlite:///'):
                sqlite_file_path = db_path[10:]
            else:
                sqlite_file_path = db_path

            dir_name = os.path.dirname(sqlite_file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            file_stream.seek(0)
            workbook_schema = openpyxl.load_workbook(file_stream, read_only=True, data_only=True)

            actual_sheet_name_schema: str
            if isinstance(sheet_name_or_index, str):
                if sheet_name_or_index not in workbook_schema.sheetnames:
                    workbook_schema.close()
                    raise ValueError(f"工作表 '{sheet_name_or_index}' 在Excel文件中未找到。")
                actual_sheet_name_schema = sheet_name_or_index
            elif isinstance(sheet_name_or_index, int):
                if not (0 <= sheet_name_or_index < len(workbook_schema.sheetnames)):
                    workbook_schema.close()
                    raise ValueError(
                        f"工作表索引 {sheet_name_or_index} 超出范围。有效范围: 0-{len(workbook_schema.sheetnames) - 1}")
                actual_sheet_name_schema = workbook_schema.sheetnames[sheet_name_or_index]
            else:
                workbook_schema.close()
                raise TypeError(f"sheet_name_or_index 必须是字符串或整数，得到 {type(sheet_name_or_index)}")

            worksheet_schema = workbook_schema[actual_sheet_name_schema]

            # 合并单元格锚点
            cell_anchor_map = {}
            if hasattr(worksheet_schema, 'merged_cells') and worksheet_schema.merged_cells:
                for merged_range_obj in worksheet_schema.merged_cells:
                    min_c, min_r, max_c, max_r = merged_range_obj.min_col, merged_range_obj.min_row, merged_range_obj.max_col, merged_range_obj.max_row
                    anchor = (min_r, min_c)
                    for r_idx in range(min_r, max_r + 1):
                        for c_idx in range(min_c, max_c + 1):
                            cell_anchor_map[(r_idx, c_idx)] = anchor

            rows_iter_schema = worksheet_schema.rows

            header_cells = next(rows_iter_schema, None)
            if not header_cells:
                workbook_schema.close()
                logging.warning(f"工作表 '{actual_sheet_name_schema}' 为空或没有表头。")
                return True, f"工作表 '{actual_sheet_name_schema}' 为空，未导入数据。"

            header = [str(cell.value) if cell.value is not None else f"Unnamed_{i}" for i, cell in
                      enumerate(header_cells)]

            sample_data_for_df, merged_value_cache_schema = get_merged_value_schema(cell_anchor_map, header, rows_iter_schema, sample_rows_for_type_inference)

            column_defs, column_type_map = get_colomn_defs(header, sample_data_for_df)

            workbook_schema.close()

            conn = sqlite3.connect(sqlite_file_path)

            cursor = conn.cursor()
            cursor.execute(f"DROP TABLE IF EXISTS '{table_name}'")
            if not column_defs:
                conn.close()
                return False, "无法确定表结构 (无表头或列定义)。"

            create_table_sql = "CREATE TABLE '{}' ({})".format(table_name, ", ".join(column_defs))
            cursor.execute(create_table_sql)
            conn.commit()

            placeholders = ', '.join(['?' for _ in header])
            col_names_for_insert = ', '.join(['"' + str(col).replace('"', '""') + '"' for col in header])
            insert_sql = "INSERT INTO '{}' ({}) VALUES ({})".format(table_name, col_names_for_insert, placeholders)

            file_stream.seek(0)
            workbook_data = openpyxl.load_workbook(file_stream, read_only=True, data_only=True)
            actual_sheet_name_data: str
            if isinstance(sheet_name_or_index, str):
                actual_sheet_name_data = sheet_name_or_index
            else:
                actual_sheet_name_data = workbook_data.sheetnames[sheet_name_or_index]

            worksheet_data = workbook_data[actual_sheet_name_data]
            rows_iter_data = worksheet_data.rows
            next(rows_iter_data, None)

            data_chunk = []
            total_rows_imported = 0
            merged_value_cache_data = {}

            logging.info(f"开始从文件流读取Excel (Pass 2), 工作表: {actual_sheet_name_data}")
            for row_cells in rows_iter_data:
                processed_row_values = []
                for idx, cell in enumerate(row_cells):
                    if cell is None or isinstance(cell, EmptyCell):
                        processed_row_values.append(None)
                        continue
                    excel_row, excel_col = cell.row, cell.column
                    cell_val = cell.value
                    final_value = None

                    anchor = cell_anchor_map.get((excel_row, excel_col))
                    if anchor:
                        if anchor == (excel_row, excel_col):
                            merged_value_cache_data[anchor] = cell_val
                            final_value = cell_val
                        else:
                            final_value = merged_value_cache_data.get(anchor)
                    else:
                        final_value = cell_val

                    if idx < len(header):
                        target_col_name = header[idx]
                        target_type = column_type_map.get(target_col_name, "TEXT")

                        if pd.isna(final_value) or final_value is None:
                            processed_row_values.append(None)
                        elif target_type == "INTEGER":
                            try:
                                processed_row_values.append(int(float(final_value)))
                            except (ValueError, TypeError):
                                processed_row_values.append(str(final_value))
                        elif target_type == "REAL":
                            try:
                                processed_row_values.append(float(final_value))
                            except (ValueError, TypeError):
                                processed_row_values.append(str(final_value))
                        else:
                            processed_row_values.append(str(final_value))
                    else:
                        processed_row_values.append(str(final_value) if final_value is not None else None)

                if len(processed_row_values) < len(header):
                    processed_row_values.extend([None] * (len(header) - len(processed_row_values)))
                elif len(processed_row_values) > len(header):
                    processed_row_values = processed_row_values[:len(header)]

                if any(v is not None for v in processed_row_values):
                    data_chunk.append(tuple(processed_row_values))

                if len(data_chunk) >= chunk_size:
                    logging.info("处理数据完毕，批量插入数据到数据库...")
                    cursor.executemany(insert_sql, data_chunk)
                    conn.commit()
                    total_rows_imported += len(data_chunk)
                    logging.info(f"已插入 {total_rows_imported} 行数据到表 {table_name}")
                    data_chunk = []

            if data_chunk:
                logging.info("处理数据完毕，批量插入数据到数据库...")
                cursor.executemany(insert_sql, data_chunk)
                conn.commit()
                total_rows_imported += len(data_chunk)
                logging.info(f"已插入最后 {len(data_chunk)} 行数据 (总计 {total_rows_imported})")

            workbook_data.close()
            conn.close()

            success_msg = f"数据已成功导入到表 {table_name} 中，共 {total_rows_imported} 行。"
            logging.info(success_msg)
            return True, success_msg

        except ValueError as ve:
            error_msg = f"值错误: {ve}"
            logging.error(error_msg, exc_info=False)
            return False, error_msg
        except TypeError as te:
            error_msg = f"类型错误: {te}"
            logging.error(error_msg, exc_info=False)
            return False, error_msg
        except Exception as e:
            error_msg = f"从文件流导入数据时发生错误: {e}"
            logging.error(error_msg, exc_info=True)
            if 'conn' in locals() and conn:
                try:
                    conn.close()
                except Exception as ex_close:
                    logging.error(f"关闭数据库连接时出错: {ex_close}")
            if 'workbook_schema' in locals() and workbook_schema._archive is not None:
                try:
                    workbook_schema.close()
                except Exception as ex_close:
                    logging.error(f"关闭 schema workbook 时出错: {ex_close}")
            if 'workbook_data' in locals() and workbook_data._archive is not None:
                try:
                    workbook_data.close()
                except Exception as ex_close:
                    logging.error(f"关闭 data workbook 时出错: {ex_close}")
            return False, error_msg


# Helper functions
def import_to_sqlite(file_path: str, table_name: str, task_id: str,
                     sheet_name=0):  # Renamed sheet_name to sheet_name_or_index
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    try:
        with open(file_path, 'rb') as f:
            file_stream = io.BytesIO(f.read())
        return ImportExcelToSQLite.do_import_to_sqlite_with_merged_cell(file_stream=file_stream,
                                                                        table_name=table_name,
                                                                        db_path=db_path,
                                                                        sheet_name_or_index=sheet_name)
    except FileNotFoundError:
        error_msg = f"文件未找到: {file_path}"
        logging.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"处理文件 {file_path} 时发生错误: {e}"
        logging.error(error_msg, exc_info=True)
        return False, error_msg


def import_to_sqlite_by_filestream(file_stream: io.BytesIO, table_name: str, task_id: str,
                                   sheet_name=0):  # Renamed sheet_name to sheet_name_or_index
    db_path = os.path.abspath(os.path.join(Config.SQLALCHEMY_DATABASE_DIRPATH, f"task_{task_id}.db_server"))
    file_stream.seek(0)
    return ImportExcelToSQLite.do_import_to_sqlite_with_merged_cell(file_stream=file_stream,
                                                                    table_name=table_name,
                                                                    db_path=db_path,
                                                                    sheet_name_or_index=sheet_name)

def get_colomn_defs(header, sample_data_for_df):
    column_defs = []
    column_type_map = {}

    if sample_data_for_df:
        sample_df = pd.DataFrame(sample_data_for_df, columns=header)
        for col_name_obj in sample_df.columns:
            col_name = str(col_name_obj)
            safe_col_name = col_name.replace('"', '""')
            series = sample_df[col_name_obj]
            is_potentially_numeric = series.dropna().apply(lambda x: isinstance(x, (int, float))).all()

            if is_potentially_numeric and pd.api.types.is_numeric_dtype(series.astype(float, errors='ignore')):
                try:
                    numeric_series = pd.to_numeric(series.dropna())
                    if numeric_series.apply(lambda x: float(x).is_integer()).all():
                        col_type = "INTEGER"
                    else:
                        col_type = "REAL"
                except (ValueError, TypeError):
                    col_type = "TEXT"
            elif pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_timedelta64_dtype(series):
                col_type = "TEXT"
            else:
                col_type = "TEXT"

            column_defs.append(f'"{safe_col_name}" {col_type}')
            column_type_map[col_name] = col_type
    else:
        for col_name_str in header:
            safe_col_name = col_name_str.replace('"', '""')
            col_type = "TEXT"
            column_defs.append(f'"{safe_col_name}" {col_type}')
            column_type_map[col_name_str] = col_type

    return column_defs, column_type_map

def get_merged_value_schema(cell_anchor_map, header, rows_iter_schema, sample_rows_for_type_inference):
    sample_data_for_df = []
    merged_value_cache_schema = {}

    for i, row_cells in enumerate(rows_iter_schema):
        if i >= sample_rows_for_type_inference:
            break

        current_row_values = []
        for cell in row_cells:
            if cell is None or isinstance(cell, EmptyCell):
                current_row_values.append(None)
                continue

            excel_row, excel_col = cell.row, cell.column
            cell_val = cell.value

            anchor = cell_anchor_map.get((excel_row, excel_col))
            if anchor:
                if anchor == (excel_row, excel_col):
                    merged_value_cache_schema[anchor] = cell_val
                    current_row_values.append(cell_val)
                else:
                    current_row_values.append(merged_value_cache_schema.get(anchor))
            else:
                current_row_values.append(cell_val)

        if len(current_row_values) < len(header):
            current_row_values.extend([None] * (len(header) - len(current_row_values)))
        elif len(current_row_values) > len(header):
            current_row_values = current_row_values[:len(header)]

        if any(v is not None for v in current_row_values):
            sample_data_for_df.append(current_row_values)
    return sample_data_for_df, merged_value_cache_schema


def get_sqlite_max_variables(conn):
    cursor = conn.cursor()
    cursor.execute('PRAGMA compile_options;')
    for option in cursor.fetchall():
        if 'MAX_VARIABLE_NUMBER' in option[0]:
            return int(option[0].split('=')[1])
    # 找不到时使用保守估计
    return 999  # 早期SQLite版本的默认值


def chunked_to_sql(df, table_name, conn, if_exists='append'):
    # 配置 SQLite 优化参数

    # 获取最大变量数
    max_vars = get_sqlite_max_variables(conn)
    # 计算安全批大小
    cols = len(df.columns)
    safe_chunk_size = max_vars // cols - 1

    # 开始事务
    conn.execute('BEGIN TRANSACTION')

    # 分批处理
    for i in range(0, len(df), safe_chunk_size):
        df.iloc[i:i + safe_chunk_size].to_sql(
            name=table_name,
            con=conn,
            if_exists='append' if i > 0 or if_exists == 'append' else if_exists,
            index=False,
            method='multi'
        )

    # 提交事务
    conn.commit()