"""
Garmin Connect 客户端模块
处理 Garmin Connect 的登录、session 管理和 API 调用
使用 garth 库进行认证
"""
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional

from garth.http import Client

logger = logging.getLogger(__name__)

# Garmin Connect API 基础 URL
GARMIN_CONNECT_API = "https://connectapi.garmin.com"
GARMIN_CONNECT_MODERN = "https://connect.garmin.com/modern/proxy"


class GarminConnectClient:
    """Garmin Connect 客户端"""

    def __init__(
        self,
        email: str,
        password: str,
        domain: str = "CN",
        session_dir: str = "data/.garth"
    ):
        """
        初始化 Garmin Connect 客户端

        Args:
            email: Garmin 邮箱
            password: Garmin 密码
            domain: 服务器区域（CN=中国，COM=国际）
            session_dir: session 保存目录
        """
        self.email = email
        self.password = password
        self.domain = domain
        self.session_dir = Path(session_dir) / email
        self._client = Client()

    def login(self) -> bool:
        """
        登录 Garmin Connect

        尝试从保存的 session 恢复，失败则重新登录

        Returns:
            是否登录成功
        """
        try:
            # 尝试恢复 session
            if self.session_dir.exists() and any(self.session_dir.iterdir()):
                logger.info(f"尝试恢复 Garmin session: {self.session_dir}")
                try:
                    self._client.load(str(self.session_dir))
                    # 验证 session 是否有效
                    username = self._client.username
                    logger.info(f"Garmin session 恢复成功，用户: {username}")
                    return True
                except Exception as e:
                    logger.warning(f"session 恢复失败: {e}，将重新登录")

            # 重新登录
            logger.info(f"正在登录 Garmin Connect: {self.email}")
            domain = "garmin.cn" if self.domain.upper() == "CN" else "garmin.com"
            self._client.configure(domain=domain)

            self._client.login(self.email, self.password)

            # 保存 session
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self._client.dump(str(self.session_dir))
            logger.info("Garmin 登录成功，session 已保存")

            return True

        except Exception as e:
            logger.error(f"Garmin 登录失败: {e}")
            return False

    def get_activities(self, start: int = 0, limit: int = 20) -> list:
        """
        获取活动列表

        Args:
            start: 起始索引
            limit: 返回数量

        Returns:
            活动列表
        """
        try:
            url = "/activitylist-service/activities/search/activities"
            params = {
                "start": start,
                "limit": limit,
            }
            activities = self._client.connectapi(url, params=params)
            logger.info(f"获取到 {len(activities) if activities else 0} 个活动")
            return activities or []
        except Exception as e:
            logger.error(f"获取活动列表失败: {e}")
            return []

    def get_activity(self, activity_id: int) -> Optional[dict]:
        """
        获取活动详情

        Args:
            activity_id: 活动 ID

        Returns:
            活动详情字典
        """
        try:
            url = f"/activity-service/activity/{activity_id}"
            activity = self._client.connectapi(url)
            return activity
        except Exception as e:
            logger.error(f"获取活动详情失败 {activity_id}: {e}")
            return None

    def _download_with_retry(self, url: str, label: str, attempts: int = 3) -> bytes | None:
        """
        下载 Garmin 文件接口，遇到临时网络错误或 Garmin 侧短暂失败时自动重试。
        """
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                data = self._client.download(url)
                if data:
                    return data
                last_error = RuntimeError("empty response")
            except Exception as exc:
                last_error = exc
            if attempt < attempts:
                wait_s = min(2 ** (attempt - 1), 4)
                logger.warning(f"{label} 第 {attempt} 次失败，{wait_s}s 后重试: {last_error}")
                time.sleep(wait_s)
        logger.error(f"{label} 重试 {attempts} 次仍失败: {last_error}")
        return None

    def download_activity_fit(self, activity_id: int, output_path: str | Path) -> bool:
        """
        下载活动的原始 FIT 文件

        Garmin Connect 返回的是 ZIP 压缩包，需要解压获取 FIT 文件

        Args:
            activity_id: 活动 ID
            output_path: 输出文件路径

        Returns:
            是否下载成功
        """
        try:
            url = f"/download-service/files/activity/{activity_id}"
            data = self._download_with_retry(url, f"下载 FIT 文件 {activity_id}")
            if not data:
                return False

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Garmin Connect 返回的是 ZIP 压缩包，需要解压
            if data[:2] == b'PK':
                # ZIP 文件头
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    # 查找 .fit 文件
                    fit_files = [f for f in zf.namelist() if f.lower().endswith('.fit')]
                    if not fit_files:
                        logger.error(f"ZIP 中未找到 FIT 文件: {activity_id}")
                        return False

                    # 提取第一个 FIT 文件
                    fit_data = zf.read(fit_files[0])
                    with open(output_path, "wb") as f:
                        f.write(fit_data)

                    logger.info(f"FIT 文件已从 ZIP 解压: {output_path}")
            else:
                # 直接保存（如果不是 ZIP）
                with open(output_path, "wb") as f:
                    f.write(data)
                logger.info(f"FIT 文件已下载: {output_path}")

            return True

        except Exception as e:
            logger.error(f"下载 FIT 文件失败 {activity_id}: {e}")
            return False

    def download_activity_tcx(self, activity_id: int, output_path: str | Path) -> bool:
        """
        下载活动的 TCX 文件，作为 FIT 解析失败时的兜底数据源。

        Args:
            activity_id: 活动 ID
            output_path: 输出文件路径

        Returns:
            是否下载成功
        """
        try:
            url = f"/download-service/export/tcx/activity/{activity_id}"
            data = self._download_with_retry(url, f"下载 TCX 文件 {activity_id}")
            if not data:
                return False
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(data)
            logger.info(f"TCX 文件已下载: {output_path}")
            return True
        except Exception as e:
            logger.error(f"下载 TCX 文件失败 {activity_id}: {e}")
            return False

    def get_activities_by_date(
        self, start_date: str, end_date: str, activity_type: str = ""
    ) -> list:
        """
        按日期范围获取活动

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            activity_type: 活动类型过滤（可选）

        Returns:
            活动列表
        """
        try:
            url = "/activitylist-service/activities/search/activities"
            all_activities = []
            start = 0
            limit = 100

            while True:
                params = {
                    "startDate": start_date,
                    "endDate": end_date,
                    "start": start,
                    "limit": limit,
                }
                if activity_type:
                    params["activityType"] = activity_type

                activities = self._client.connectapi(url, params=params)

                if not activities:
                    break

                all_activities.extend(activities)

                if len(activities) < limit:
                    break

                start += limit

            logger.info(f"按日期范围获取到 {len(all_activities)} 个活动")
            return all_activities

        except Exception as e:
            logger.error(f"按日期获取活动失败: {e}")
            return []

    # ==================== 健康数据 API ====================

    def get_daily_steps(self, start_date: str, end_date: str) -> list:
        """
        获取每日步数数据

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            步数数据列表
        """
        try:
            url = f"/usersummary-service/stats/steps/daily/{start_date}/{end_date}"
            data = self._client.connectapi(url)
            logger.info(f"获取到 {len(data) if data else 0} 天步数数据")
            return data or []
        except Exception as e:
            logger.error(f"获取步数数据失败: {e}")
            return []

    def get_daily_summary(self, cdate: str) -> Optional[dict]:
        """
        获取 Garmin 每日汇总，作为步数区间接口无数据时的备用来源。

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            每日汇总字典
        """
        try:
            url = "/usersummary-service/usersummary/daily/"
            params = {"calendarDate": cdate}
            data = self._client.connectapi(url, params=params)
            logger.info(f"获取到 {cdate} 每日汇总数据")
            return data
        except Exception as e:
            logger.error(f"获取每日汇总失败 {cdate}: {e}")
            return None

    def get_heart_rates(self, cdate: str) -> Optional[dict]:
        """
        获取指定日期的心率数据（全天心率）

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            心率数据字典
        """
        try:
            url = "/wellness-service/wellness/dailyHeartRate"
            params = {"date": cdate}
            data = self._client.connectapi(url, params=params)
            logger.info(f"获取到 {cdate} 心率数据")
            return data
        except Exception as e:
            logger.error(f"获取心率数据失败 {cdate}: {e}")
            return None

    def get_resting_heart_rate(self, cdate: str) -> Optional[dict]:
        """
        获取指定日期的静息心率

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            静息心率数据字典
        """
        try:
            url = "/userstats-service/wellness/daily"
            params = {
                "fromDate": cdate,
                "untilDate": cdate,
                "metricId": 60,
            }
            data = self._client.connectapi(url, params=params)
            logger.info(f"获取到 {cdate} 静息心率数据")
            return data
        except Exception as e:
            logger.error(f"获取静息心率数据失败 {cdate}: {e}")
            return None

    def get_hrv_data(self, cdate: str) -> Optional[dict]:
        """
        获取指定日期的HRV（心率变异性）数据

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            HRV数据字典
        """
        try:
            url = f"/hrv-service/hrv/{cdate}"
            data = self._client.connectapi(url)
            logger.info(f"获取到 {cdate} HRV数据")
            return data
        except Exception as e:
            logger.error(f"获取HRV数据失败 {cdate}: {e}")
            return None

    def get_sleep_data(self, cdate: str) -> Optional[dict]:
        """
        获取指定日期的睡眠数据

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            睡眠数据字典
        """
        try:
            url = "/wellness-service/wellness/dailySleepData"
            params = {"date": cdate, "nonSleepBufferMinutes": 60}
            data = self._client.connectapi(url, params=params)
            logger.info(f"获取到 {cdate} 睡眠数据")
            return data
        except Exception as e:
            logger.error(f"获取睡眠数据失败 {cdate}: {e}")
            return None

    def get_body_composition(self, start_date: str, end_date: str) -> Optional[dict]:
        """
        获取体重/身体成分数据

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            身体成分数据字典
        """
        try:
            url = "/weight-service/weight/dateRange"
            params = {"startDate": start_date, "endDate": end_date}
            data = self._client.connectapi(url, params=params)
            logger.info(f"获取到 {start_date} ~ {end_date} 身体成分数据")
            return data
        except Exception as e:
            logger.error(f"获取身体成分数据失败: {e}")
            return None

    def get_spo2_data(self, cdate: str) -> Optional[dict]:
        """
        获取指定日期的SpO2（血氧饱和度）数据

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            SpO2数据字典
        """
        try:
            url = f"/wellness-service/wellness/daily/spo2/{cdate}"
            data = self._client.connectapi(url)
            logger.info(f"获取到 {cdate} SpO2数据")
            return data
        except Exception as e:
            logger.error(f"获取SpO2数据失败 {cdate}: {e}")
            return None

    def get_stress_data(self, cdate: str) -> Optional[dict]:
        """
        获取指定日期的压力数据

        Args:
            cdate: 日期（YYYY-MM-DD）

        Returns:
            压力数据字典
        """
        try:
            url = f"/wellness-service/wellness/dailyStress/{cdate}"
            data = self._client.connectapi(url)
            logger.info(f"获取到 {cdate} 压力数据")
            return data
        except Exception as e:
            logger.error(f"获取压力数据失败 {cdate}: {e}")
            return None
