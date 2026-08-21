#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 news 表的 published 字段格式
旧格式: Wed, 12 Aug 2026 00:00:00 -0400
新格式: 2026-08-19T04:00:00+00:00
"""

import sqlite3
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
import logging
from pathlib import Path

# ============ 配置 ============
DB_PATH = "storage/news.db"  # 替换为你的数据库路径
TABLE_NAME = "news"
COLUMN_NAME = "published"
BATCH_SIZE = 1000  # 每批处理数量
BACKUP_TABLE = "news_backup_before_format_fix"  # 备份表名

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('published_fix.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def is_old_format(text: str) -> bool:
    """
    判断是否为旧格式（包含英文月份缩写）
    新格式: 2026-08-19T04:00:00+00:00
    旧格式: Wed, 12 Aug 2026 00:00:00 -0400
    """
    if not text:
        return False
    
    # 新格式特征: 以 4位数字-2位数字-2位数字T 开头
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$', text):
        return False
    
    # 旧格式特征: 包含英文月份缩写
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    if any(month in text for month in months):
        return True
    
    # 如果都不匹配，记录警告但跳过
    return False


def convert_to_new_format(old_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    转换旧格式到新格式
    返回: (新格式, 错误信息) 成功时错误信息为 None
    """
    if not old_text:
        return None, "空值"
    
    # 如果已经是新格式，直接返回
    if not is_old_format(old_text):
        return old_text, None
    
    try:
        # 解析旧格式: Wed, 12 Aug 2026 00:00:00 -0400
        dt = datetime.strptime(old_text.strip(), '%a, %d %b %Y %H:%M:%S %z')
        
        # 转换为 UTC+0
        dt_utc = dt.astimezone(timezone.utc)
        
        # 格式化为目标格式
        new_format = dt_utc.strftime('%Y-%m-%dT%H:%M:%S+00:00')
        
        return new_format, None
        
    except ValueError as e:
        return None, f"解析失败: {e}"
    except Exception as e:
        return None, f"未知错误: {e}"


def create_backup(conn: sqlite3.Connection) -> bool:
    """创建备份表"""
    try:
        cursor = conn.cursor()
        
        # 检查备份表是否已存在
        cursor.execute(f"""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='{BACKUP_TABLE}'
        """)
        
        if cursor.fetchone():
            logger.warning(f"备份表 {BACKUP_TABLE} 已存在，跳过备份")
            return True
        
        # 创建备份
        logger.info(f"正在创建备份表 {BACKUP_TABLE}...")
        cursor.execute(f"""
            CREATE TABLE {BACKUP_TABLE} AS 
            SELECT * FROM {TABLE_NAME}
        """)
        conn.commit()
        
        # 验证备份
        cursor.execute(f"SELECT COUNT(*) FROM {BACKUP_TABLE}")
        count = cursor.fetchone()[0]
        logger.info(f"✅ 备份完成，共备份 {count} 条记录")
        return True
        
    except Exception as e:
        logger.error(f"❌ 备份失败: {e}")
        return False


def count_records(conn: sqlite3.Connection, condition: str = "") -> int:
    """统计记录数"""
    cursor = conn.cursor()
    where_clause = f"WHERE {condition}" if condition else ""
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME} {where_clause}")
    return cursor.fetchone()[0]


def get_old_records(conn: sqlite3.Connection, limit: int = None, offset: int = 0) -> list:
    """分批获取旧格式记录"""
    cursor = conn.cursor()
    
    # 找出所有旧格式记录（包含英文月份）
    months_condition = " OR ".join([
        f"{COLUMN_NAME} LIKE '%{month}%'" 
        for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    ])
    
    # 同时排除已经是新格式的
    sql = f"""
        SELECT rowid, {COLUMN_NAME}
        FROM {TABLE_NAME}
        WHERE ({months_condition})
          AND {COLUMN_NAME} NOT LIKE '%-%T%:%:%+%'
          AND {COLUMN_NAME} IS NOT NULL
          AND {COLUMN_NAME} != ''
    """
    
    if limit:
        sql += f" LIMIT {limit} OFFSET {offset}"
    
    cursor.execute(sql)
    return cursor.fetchall()


def fix_published_field(conn: sqlite3.Connection, dry_run: bool = True) -> dict:
    """
    主修复函数
    dry_run=True: 只分析不修改
    dry_run=False: 执行修改
    """
    stats = {
        'total_old': 0,
        'converted': 0,
        'failed': 0,
        'skipped': 0,
        'errors': []
    }
    
    # 1. 统计需要处理的记录数
    logger.info("📊 正在扫描旧格式数据...")
    old_records = get_old_records(conn)
    stats['total_old'] = len(old_records)
    
    if stats['total_old'] == 0:
        logger.info("✅ 没有需要转换的旧格式数据！")
        return stats
    
    logger.info(f"📊 发现 {stats['total_old']} 条旧格式记录")
    
    if dry_run:
        # 预览前几条
        logger.info("\n📋 预览前 10 条待转换数据:")
        for i, (rowid, published) in enumerate(old_records[:10], 1):
            new_format, error = convert_to_new_format(published)
            status = "✅" if new_format else "❌"
            logger.info(f"  {i}. rowid={rowid}")
            logger.info(f"     旧: {published}")
            logger.info(f"     新: {new_format or error}")
            logger.info(f"     状态: {status}")
        return stats
    
    # 2. 执行转换（分批处理）
    logger.info("\n🔄 开始转换...")
    cursor = conn.cursor()
    
    for i, (rowid, published) in enumerate(old_records, 1):
        new_format, error = convert_to_new_format(published)
        
        if new_format:
            try:
                cursor.execute(
                    f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = ? WHERE rowid = ?",
                    (new_format, rowid)
                )
                stats['converted'] += 1
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append({
                    'rowid': rowid,
                    'old_value': published,
                    'error': str(e)
                })
        else:
            stats['failed'] += 1
            stats['errors'].append({
                'rowid': rowid,
                'old_value': published,
                'error': error
            })
        
        # 每批提交一次
        if i % BATCH_SIZE == 0:
            conn.commit()
            logger.info(f"  进度: {i}/{stats['total_old']} ({i*100//stats['total_old']}%)")
    
    # 最后一批提交
    conn.commit()
    logger.info(f"  进度: {stats['total_old']}/{stats['total_old']} (100%)")
    
    return stats


def verify_result(conn: sqlite3.Connection) -> dict:
    """验证修复结果"""
    cursor = conn.cursor()
    
    # 统计新旧格式数量
    # 新格式: 匹配 YYYY-MM-DDTHH:MM:SS+00:00
    cursor.execute(f"""
        SELECT COUNT(*) FROM {TABLE_NAME}
        WHERE {COLUMN_NAME} LIKE '%-%T%:%:%+%'
    """)
    new_count = cursor.fetchone()[0]
    
    # 旧格式: 包含英文月份
    months_condition = " OR ".join([
        f"{COLUMN_NAME} LIKE '%{month}%'" 
        for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    ])
    cursor.execute(f"""
        SELECT COUNT(*) FROM {TABLE_NAME}
        WHERE ({months_condition})
          AND {COLUMN_NAME} NOT LIKE '%-%T%:%:%+%'
    """)
    old_count = cursor.fetchone()[0]
    
    # 总记录数
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    total = cursor.fetchone()[0]
    
    return {
        'total': total,
        'new_format': new_count,
        'old_format': old_count,
        'other': total - new_count - old_count
    }


def restore_from_backup(conn: sqlite3.Connection):
    """从备份恢复数据"""
    try:
        cursor = conn.cursor()
        logger.warning("⚠️ 正在从备份恢复...")
        
        # 检查备份表是否存在
        cursor.execute(f"""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='{BACKUP_TABLE}'
        """)
        
        if not cursor.fetchone():
            logger.error(f"❌ 备份表 {BACKUP_TABLE} 不存在")
            return False
        
        # 恢复数据
        cursor.execute(f"""
            UPDATE {TABLE_NAME}
            SET {COLUMN_NAME} = (
                SELECT {COLUMN_NAME} 
                FROM {BACKUP_TABLE} 
                WHERE {BACKUP_TABLE}.rowid = {TABLE_NAME}.rowid
            )
            WHERE EXISTS (
                SELECT 1 
                FROM {BACKUP_TABLE} 
                WHERE {BACKUP_TABLE}.rowid = {TABLE_NAME}.rowid
            )
        """)
        conn.commit()
        
        logger.info("✅ 恢复成功")
        return True
        
    except Exception as e:
        logger.error(f"❌ 恢复失败: {e}")
        return False


def main():
    """主函数"""
    # 检查数据库文件是否存在
    if not Path(DB_PATH).exists():
        logger.error(f"❌ 数据库文件不存在: {DB_PATH}")
        return
    
    # 连接数据库
    logger.info(f"📂 连接数据库: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        # 1. 先备份
        if not create_backup(conn):
            logger.error("❌ 备份失败，终止执行")
            return
        
        # 2. 先做 Dry Run（预览）
        logger.info("\n" + "="*60)
        logger.info("🔍 阶段1: 预览模式 (DRY RUN)")
        logger.info("="*60)
        stats = fix_published_field(conn, dry_run=True)
        
        if stats['total_old'] == 0:
            return
        
        # 3. 询问是否继续
        print("\n" + "="*60)
        print(f"📊 将转换 {stats['total_old']} 条记录")
        print("⚠️  确认继续？(输入 'yes' 继续，其他任意键退出)")
        print("="*60)
        
        user_input = input(">>> ").strip().lower()
        if user_input != 'yes':
            logger.info("❌ 用户取消操作")
            return
        
        # 4. 执行转换
        logger.info("\n" + "="*60)
        logger.info("🔄 阶段2: 执行转换")
        logger.info("="*60)
        stats = fix_published_field(conn, dry_run=False)
        
        # 5. 验证结果
        logger.info("\n" + "="*60)
        logger.info("✅ 阶段3: 验证结果")
        logger.info("="*60)
        verify = verify_result(conn)
        logger.info(f"📊 总记录数: {verify['total']}")
        logger.info(f"   ✅ 新格式: {verify['new_format']}")
        logger.info(f"   ⚠️  旧格式: {verify['old_format']}")
        logger.info(f"   📝 其他格式: {verify['other']}")
        
        # 6. 显示错误汇总
        if stats['errors']:
            logger.warning(f"\n⚠️  共有 {len(stats['errors'])} 条记录转换失败:")
            for err in stats['errors'][:10]:  # 只显示前10条
                logger.warning(f"  rowid={err['rowid']}, 错误: {err['error']}")
            if len(stats['errors']) > 10:
                logger.warning(f"  ... 还有 {len(stats['errors'])-10} 条错误，详见日志文件")
        
        # 7. 最终统计
        logger.info("\n" + "="*60)
        logger.info("📊 转换完成统计:")
        logger.info(f"   ✅ 成功: {stats['converted']}")
        logger.info(f"   ❌ 失败: {stats['failed']}")
        logger.info(f"   ⏭️  跳过: {stats['skipped']}")
        logger.info("="*60)
        
        if verify['old_format'] == 0:
            logger.info("🎉 所有数据已统一为新格式！")
        else:
            logger.warning(f"⚠️  仍有 {verify['old_format']} 条旧格式数据需要手动处理")
        
        # 8. 询问是否删除备份
        if verify['old_format'] == 0:
            print("\n是否删除备份表？(输入 'drop' 删除备份，其他键保留)")
            if input(">>> ").strip().lower() == 'drop':
                cursor = conn.cursor()
                cursor.execute(f"DROP TABLE {BACKUP_TABLE}")
                conn.commit()
                logger.info("✅ 备份表已删除")
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️ 用户中断操作")
        logger.info("数据未提交，可安全退出")
    except Exception as e:
        logger.error(f"❌ 执行出错: {e}")
        import traceback
        traceback.print_exc()
        
        # 出错时提示恢复
        print("\n是否从备份恢复？(输入 'restore' 恢复)")
        if input(">>> ").strip().lower() == 'restore':
            restore_from_backup(conn)
    finally:
        conn.close()
        logger.info("\n📂 数据库连接已关闭")


if __name__ == "__main__":
    main()