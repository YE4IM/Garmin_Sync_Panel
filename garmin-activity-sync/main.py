"""
Garmin 运动数据本地同步工具 - CLI 入口
支持本地 FIT 导入、Garmin Connect 同步、JSON 导出等功能
"""
import argparse
import logging
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import setup_logger
from utils.path_utils import get_project_root


def cmd_init(args):
    """初始化数据库和目录结构"""
    from core.config import ConfigManager
    from core.database import Database
    from utils.path_utils import get_db_path, get_data_dir, get_log_dir, get_export_dir, get_fit_download_dir

    config_mgr = ConfigManager(args.config)
    try:
        config = config_mgr.load()
    except FileNotFoundError:
        print(f"错误: 配置文件不存在: {args.config}")
        print(f"请复制 config.example.json 为 {args.config} 并填入您的配置")
        sys.exit(1)

    # 创建目录
    get_data_dir(config)
    get_log_dir(config)
    get_export_dir(config)
    get_fit_download_dir(config)

    # 初始化数据库
    db_path = get_db_path(config)
    db = Database(db_path)
    db.init_db()
    db.close()

    print(f"初始化完成:")
    print(f"  数据库: {db_path}")
    print(f"  数据目录: {get_data_dir(config)}")
    print(f"  导出目录: {get_export_dir(config)}")
    print(f"  FIT 下载目录: {get_fit_download_dir(config)}")


def cmd_sync(args):
    """从 Garmin Connect 同步活动"""
    from core.config import ConfigManager
    from core.sync_service import sync_from_garmin

    config_mgr = ConfigManager(args.config)
    try:
        config = config_mgr.load()
    except FileNotFoundError:
        print(f"错误: 配置文件不存在: {args.config}")
        print(f"请复制 config.example.json 为 {args.config} 并填入您的配置")
        sys.exit(1)

    if not config_mgr.validate():
        print("错误: Garmin 配置不完整，请检查 config.json")
        sys.exit(1)

    days = args.days or 30
    export = args.export or False

    print(f"正在从 Garmin Connect 同步最近 {days} 天的活动...")
    result = sync_from_garmin(days, config, export=export)

    _print_sync_result(result)


def cmd_import_fit(args):
    """导入本地 FIT 文件"""
    from core.config import ConfigManager
    from core.sync_service import sync_from_local

    config_mgr = ConfigManager(args.config)
    try:
        config = config_mgr.load()
    except FileNotFoundError:
        print(f"错误: 配置文件不存在: {args.config}")
        print(f"请复制 config.example.json 为 {args.config} 并填入您的配置")
        sys.exit(1)

    directory = args.dir
    if not directory:
        print("错误: 请指定 FIT 文件目录 --dir /path/to/FIT")
        sys.exit(1)

    export = args.export or False

    print(f"正在从 {directory} 导入 FIT 文件...")
    result = sync_from_local(directory, config, export=export)

    _print_sync_result(result)


def cmd_export(args):
    """导出 PiDesk JSON"""
    from core.config import ConfigManager
    from core.sync_service import export_json

    config_mgr = ConfigManager(args.config)
    try:
        config = config_mgr.load()
    except FileNotFoundError:
        print(f"错误: 配置文件不存在: {args.config}")
        print(f"请复制 config.example.json 为 {args.config} 并填入您的配置")
        sys.exit(1)

    success = export_json(config)
    if success:
        print("PiDesk JSON 导出成功")
    else:
        print("PiDesk JSON 导出失败")
        sys.exit(1)


def cmd_status(args):
    """显示同步状态"""
    from core.config import ConfigManager
    from core.sync_service import get_status, get_health_status
    from utils.time_utils import format_pace, format_duration, format_distance

    config_mgr = ConfigManager(args.config)
    try:
        config = config_mgr.load()
    except FileNotFoundError:
        print(f"错误: 配置文件不存在: {args.config}")
        print(f"请复制 config.example.json 为 {args.config} 并填入您的配置")
        sys.exit(1)

    status = get_status(config)

    print("=" * 60)
    print("Garmin 运动数据同步状态")
    print("=" * 60)

    print(f"\n数据库: {status['db_path']}")
    print(f"总活动数: {status['total_activities']}")

    # 最近一次运动
    last = status.get("last_activity")
    if last:
        print(f"\n最近运动:")
        print(f"  名称: {last.get('name', 'N/A')}")
        print(f"  类型: {last.get('sport_type', 'N/A')}")
        print(f"  时间: {last.get('start_time', 'N/A')}")
        print(f"  距离: {format_distance(last.get('distance_m', 0))}")
        print(f"  时长: {format_duration(last.get('duration_s', 0))}")
        print(f"  配速: {format_pace(last.get('avg_pace_s_per_km', 0))}/km")
        print(f"  心率: {last.get('avg_hr', 0)} bpm")
        print(f"  卡路里: {last.get('calories', 0)} kcal")
    else:
        print("\n暂无运动记录")

    # 本周统计
    weekly = status.get("weekly_stats", {})
    print(f"\n本周统计:")
    print(f"  活动次数: {weekly.get('total_activities', 0)}")
    print(f"  总距离: {weekly.get('total_distance_km', 0)} km")
    print(f"  总时长: {weekly.get('total_duration_min', 0)} min")
    print(f"  总卡路里: {weekly.get('total_calories', 0)} kcal")

    # 本月统计
    monthly = status.get("monthly_stats", {})
    print(f"\n本月统计:")
    print(f"  活动次数: {monthly.get('total_activities', 0)}")
    print(f"  总距离: {monthly.get('total_distance_km', 0)} km")
    print(f"  总时长: {monthly.get('total_duration_min', 0)} min")
    print(f"  总卡路里: {monthly.get('total_calories', 0)} kcal")

    # 运动类型统计
    sport_stats = status.get("sport_type_stats", [])
    if sport_stats:
        print(f"\n运动类型分布:")
        for stat in sport_stats:
            sport = stat.get("sport_type", "unknown")
            count = stat.get("count", 0)
            dist = stat.get("total_distance_m", 0) / 1000
            print(f"  {sport}: {count} 次, {dist:.1f} km")

    # 健康数据状态
    if args.health:
        health_status = get_health_status(config)
        counts = health_status.get("counts", {})
        latest = health_status.get("latest", {})

        print(f"\n健康数据统计:")
        print(f"  步数记录: {counts.get('daily_steps', 0)} 条")
        print(f"  心率记录: {counts.get('heart_rate_data', 0)} 条")
        print(f"  HRV记录: {counts.get('hrv_data', 0)} 条")
        print(f"  睡眠记录: {counts.get('sleep_data', 0)} 条")
        print(f"  体重记录: {counts.get('weight_data', 0)} 条")
        print(f"  SpO2记录: {counts.get('spo2_data', 0)} 条")

        # 最新健康数据
        if latest.get('steps'):
            s = latest['steps']
            print(f"\n最新步数 ({s.get('date', '')}):")
            print(f"  步数: {s.get('steps', 0)}")
            print(f"  距离: {s.get('distance_m', 0) / 1000:.1f} km")

        if latest.get('heart_rate'):
            hr = latest['heart_rate']
            print(f"\n最新心率 ({hr.get('date', '')}):")
            print(f"  静息心率: {hr.get('resting_hr', 0)} bpm")
            print(f"  平均心率: {hr.get('avg_hr', 0)} bpm")

        if latest.get('hrv'):
            hrv = latest['hrv']
            print(f"\n最新HRV ({hrv.get('date', '')}):")
            print(f"  7天平均: {hrv.get('weekly_avg', 0)} ms")
            print(f"  昨晚平均: {hrv.get('last_night_avg', 0)} ms")
            print(f"  状态: {hrv.get('status', 'N/A')}")

        if latest.get('sleep'):
            slp = latest['sleep']
            total_h = slp.get('total_sleep_s', 0) / 3600
            print(f"\n最新睡眠 ({slp.get('date', '')}):")
            print(f"  总时长: {total_h:.1f} 小时")
            print(f"  睡眠得分: {slp.get('sleep_score', 0)}")

        if latest.get('weight'):
            w = latest['weight']
            print(f"\n最新体重 ({w.get('date', '')}):")
            print(f"  体重: {w.get('weight_kg', 0)} kg")
            print(f"  BMI: {w.get('bmi', 0)}")
            print(f"  体脂率: {w.get('body_fat_pct', 0)}%")

        if latest.get('spo2'):
            sp = latest['spo2']
            print(f"\n最新SpO2 ({sp.get('date', '')}):")
            print(f"  平均血氧: {sp.get('avg_spo2', 0)}%")

    print("\n" + "=" * 60)


def cmd_sync_health(args):
    """从 Garmin Connect 同步健康数据"""
    from core.config import ConfigManager
    from core.sync_service import sync_health_data

    config_mgr = ConfigManager(args.config)
    try:
        config = config_mgr.load()
    except FileNotFoundError:
        print(f"错误: 配置文件不存在: {args.config}")
        print(f"请复制 config.example.json 为 {args.config} 并填入您的配置")
        sys.exit(1)

    if not config_mgr.validate():
        print("错误: Garmin 配置不完整，请检查 config.json")
        sys.exit(1)

    days = args.days or 7

    # 解析数据类型
    data_types = None
    if args.types:
        valid_types = ['steps', 'heart_rate', 'hrv', 'sleep', 'weight', 'spo2']
        data_types = [t.strip() for t in args.types.split(',')]
        for t in data_types:
            if t not in valid_types:
                print(f"错误: 无效的数据类型 '{t}'")
                print(f"有效类型: {', '.join(valid_types)}")
                sys.exit(1)

    print(f"正在从 Garmin Connect 同步最近 {days} 天的健康数据...")
    if data_types:
        print(f"数据类型: {', '.join(data_types)}")
    else:
        print("数据类型: 所有 (步数/心率/HRV/睡眠/体重/SpO2)")

    result = sync_health_data(days, config, data_types)

    print("\n" + "=" * 60)
    print("健康数据同步结果")
    print("=" * 60)

    if result.get("success"):
        print("状态: 成功")
    else:
        print("状态: 部分失败")

    synced = result.get("synced", {})
    print(f"\n同步记录数:")
    for data_type, count in synced.items():
        type_names = {
            'steps': '步数',
            'heart_rate': '心率',
            'hrv': 'HRV',
            'sleep': '睡眠',
            'weight': '体重',
            'spo2': 'SpO2'
        }
        print(f"  {type_names.get(data_type, data_type)}: {count} 条")

    errors = result.get("errors")
    if errors:
        print(f"\n错误信息:")
        for error in errors:
            print(f"  - {error}")

    print("=" * 60)

    if not result.get("success"):
        sys.exit(1)


def _print_sync_result(result):
    """打印同步结果"""
    print("\n" + "=" * 60)
    print(f"同步结果 ({result.source})")
    print("=" * 60)
    print(f"  总文件数: {result.total_files}")
    print(f"  新增活动: {result.new_activities}")
    print(f"  跳过(已存在): {result.skipped}")
    print(f"  失败: {result.failed}")

    if result.error_message:
        print(f"  错误信息: {result.error_message}")

    print("=" * 60)

    if result.failed > 0:
        sys.exit(1)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(
        description="Garmin 运动数据本地同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py init                          初始化数据库和目录
  python main.py sync --days 30                同步最近 30 天活动
  python main.py sync --days 30 --export       同步并自动导出 JSON
  python main.py import-fit --dir /path/to/FIT 导入本地 FIT 文件
  python main.py export                        导出 PiDesk JSON
  python main.py status                        查看同步状态
  python main.py status --health               查看健康数据状态
  python main.py sync-health --days 7          同步最近 7 天健康数据
  python main.py sync-health --days 30 --types steps,sleep  同步指定类型
        """
    )

    parser.add_argument(
        "--config",
        default="config.json",
        help="配置文件路径 (默认: config.json)"
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # init 命令
    subparsers.add_parser("init", help="初始化数据库和目录结构")

    # sync 命令
    sync_parser = subparsers.add_parser("sync", help="从 Garmin Connect 同步活动")
    sync_parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="同步最近多少天的活动 (默认: 30)"
    )
    sync_parser.add_argument(
        "--export",
        action="store_true",
        help="同步后自动导出 PiDesk JSON"
    )

    # import-fit 命令
    import_parser = subparsers.add_parser("import-fit", help="导入本地 FIT 文件")
    import_parser.add_argument(
        "--dir",
        required=True,
        help="FIT 文件目录路径"
    )
    import_parser.add_argument(
        "--export",
        action="store_true",
        help="导入后自动导出 PiDesk JSON"
    )

    # export 命令
    subparsers.add_parser("export", help="导出 PiDesk JSON")

    # status 命令
    status_parser = subparsers.add_parser("status", help="查看同步状态")
    status_parser.add_argument(
        "--health",
        action="store_true",
        help="显示健康数据状态"
    )

    # sync-health 命令
    health_parser = subparsers.add_parser("sync-health", help="从 Garmin Connect 同步健康数据")
    health_parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="同步最近多少天的数据 (默认: 7)"
    )
    health_parser.add_argument(
        "--types",
        type=str,
        help="要同步的数据类型，逗号分隔 (steps,heart_rate,hrv,sleep,weight,spo2)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 设置日志
    setup_logger(log_level=logging.INFO)

    # 执行命令
    commands = {
        "init": cmd_init,
        "sync": cmd_sync,
        "import-fit": cmd_import_fit,
        "export": cmd_export,
        "status": cmd_status,
        "sync-health": cmd_sync_health,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
