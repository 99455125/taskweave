import openpyxl
import random
import string
from datetime import datetime, timedelta


def random_string(length=10):
    """生成指定长度的随机字符串"""
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))


def random_date(start_date, end_date):
    """在指定日期范围内生成随机日期"""
    time_between_dates = end_date - start_date
    days_between_dates = time_between_dates.days
    random_number_of_days = random.randrange(days_between_dates)
    random_date_obj = start_date + timedelta(days=random_number_of_days)
    return random_date_obj


def generate_excel_data(filename="insurance_policies.xlsx", num_rows=4000000):
    """生成包含保单数据的Excel文件"""
    workbook = openpyxl.Workbook()
    sheet = workbook.active

    # 定义表头
    headers = [f"Column_{i + 1}" for i in range(18)]  # 18个普通列
    headers.insert(random.randint(0, 17), "Numeric_Column_1")  # 插入第一个数字列
    headers.insert(random.randint(0, 18), "Numeric_Column_2")  # 插入第二个数字列
    headers.insert(random.randint(0, 19), "Date_Column_1")  # 插入第一个日期列
    headers.insert(random.randint(0, 20), "Date_Column_2")  # 插入第二个日期列

    # 确保总共20列，如果因为插入位置导致列数不足或过多，需要调整
    # 这里简化处理，假设插入后正好是20列，实际应用中可能需要更复杂的逻辑保证列数
    final_headers = headers[:20]  # 取前20个作为最终表头

    # 重新获取数字列和日期列的实际索引
    numeric_col_indices = [i for i, h in enumerate(final_headers) if "Numeric_Column" in h]
    date_col_indices = [i for i, h in enumerate(final_headers) if "Date_Column" in h]

    sheet.append(final_headers)

    # 定义日期范围
    start_date = datetime(2000, 1, 1)
    end_date = datetime(2023, 12, 31)

    print(f"开始生成 {num_rows} 行数据...")

    for i in range(num_rows):
        row_data = []
        for col_idx in range(len(final_headers)):
            if col_idx in numeric_col_indices:
                row_data.append(random.randint(1000, 1000000))  # 随机整数
            elif col_idx in date_col_indices:
                row_data.append(random_date(start_date, end_date))
            else:
                row_data.append(random_string(random.randint(5, 15)))  # 其他列为随机字符串
        sheet.append(row_data)

        if (i + 1) % 100000 == 0:  # 每生成10万行打印一次进度
            print(f"已生成 {i + 1} 行...")

    print(f"数据生成完毕，正在保存到文件 '{filename}'...")
    workbook.save(filename)
    print(f"文件 '{filename}' 保存成功。")


if __name__ == "__main__":
    # 为了演示，我们生成一个较小的文件，例如1000行
    # 如果要生成400万行，请取消注释下一行并注释掉演示行
    # generate_excel_data(num_rows=4000000)
    generate_excel_data(filename="/Users/piaochongmogu/PycharmProjects/smart_excel/docs/sample_insurance_policies1m.xlsx", num_rows=1000000)
    print("示例文件 'sample_insurance_policies.xlsx' 已生成。")
    print("要生成400万行数据，请修改脚本中的 num_rows 参数。")