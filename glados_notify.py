import requests
import json
import os
import logging
import datetime
from typing import Dict, List, Optional, Tuple
from pypushdeer import PushDeer

# ---------------------- 时间设置 ----------------------
def beijing_time_converter(timestamp):
    utc_dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    beijing_dt = utc_dt.astimezone(beijing_tz)
    return beijing_dt.timetuple()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    if hasattr(handler, 'formatter') and handler.formatter is not None:
        handler.formatter.converter = beijing_time_converter

logger = logging.getLogger(__name__)

# ---------------------- 环境变量 ----------------------
ENV_PUSH_KEY = "PUSHDEER_SENDKEY"
ENV_COOKIES = "GLADOS_COOKIES"
ENV_EXCHANGE_PLAN = "GLADOS_EXCHANGE_PLAN"
ENV_TG_BOT_TOKEN = "TG_BOT_TOKEN"
ENV_TG_CHAT_ID = "TG_CHAT_ID"

# ---------------------- API 配置 ----------------------
CHECKIN_URL = "https://glados.cloud/api/user/checkin"
STATUS_URL = "https://glados.cloud/api/user/status"
POINTS_URL = "https://glados.cloud/api/user/points"
EXCHANGE_URL = "https://glados.cloud/api/user/exchange"

CHECKIN_DATA = {"token": "glados.cloud"} 

HEADERS_TEMPLATE = {
    'referer': 'https://glados.cloud/console/checkin',
    'origin': "https://glados.cloud",
    'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
    'content-type': 'application/json;charset=UTF-8'
}

EXCHANGE_POINTS = {"plan100": 100, "plan200": 200, "plan500": 500} 

# ---------------------- 配置加载 ----------------------
def load_config() -> Tuple[str, List[str], str, str, str]:
    push_key = os.environ.get(ENV_PUSH_KEY, "")
    cookies_env = os.environ.get(ENV_COOKIES, "")
    exchange_plan = os.environ.get(ENV_EXCHANGE_PLAN, "plan500")
    tg_token = os.environ.get(ENV_TG_BOT_TOKEN, "")
    tg_chat_id = os.environ.get(ENV_TG_CHAT_ID, "")

    cookies_list = [c.strip() for c in cookies_env.split('&') if c.strip()]

    if exchange_plan not in EXCHANGE_POINTS:
        logger.warning(f"兑换计划 {exchange_plan} 无效，使用默认 plan500")
        exchange_plan = "plan500"

    logger.info(f"共加载 {len(cookies_list)} 个 Cookie。")
    return push_key, cookies_list, exchange_plan, tg_token, tg_chat_id

# ---------------------- HTTP 请求 ----------------------
def make_request(url: str, method: str, headers: Dict[str, str], data: Optional[Dict] = None, cookies: str = "") -> Optional[requests.Response]:
    session_headers = headers.copy()
    session_headers['cookie'] = cookies
    try:
        if method.upper() == 'POST':
            response = requests.post(url, headers=session_headers, data=json.dumps(data))
        elif method.upper() == 'GET':
            response = requests.get(url, headers=session_headers)
        else:
            logger.error(f"不支持 HTTP 方法: {method}")
            return None

        if not response.ok:
            logger.warning(f"请求 {url} 失败，状态码 {response.status_code}，内容: {response.text}")
            return None
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"请求 {url} 出现异常: {e}")
        return None

# ---------------------- 签到 & 兑换 ----------------------
def checkin_and_process(cookie: str, exchange_plan: str) -> Tuple[str, str, str, str, str]:
    status_msg = "签到请求失败"
    points_gained = "0"
    remaining_days = "获取剩余天数失败"
    remaining_points = "获取剩余积分失败"
    exchange_msg = "兑换跳过或失败"

    checkin_response = make_request(CHECKIN_URL, 'POST', HEADERS_TEMPLATE, CHECKIN_DATA, cookies=cookie)
    if not checkin_response:
        return status_msg, points_gained, remaining_days, remaining_points, exchange_msg

    try:
        checkin_data = checkin_response.json()
        response_message = checkin_data.get('message', '无消息字段')
        points_gained = str(checkin_data.get('points', 0))
        if "Checkin! Got" in response_message:
            status_msg = f"签到成功，获得 {points_gained} 积分"
        elif "Checkin Repeats!" in response_message:
            status_msg = "重复签到，明天再来"
            points_gained = "0"
        else:
            status_msg = f"签到失败: {response_message}"
            points_gained = "0"
    except:
        return status_msg, points_gained, remaining_days, remaining_points, exchange_msg

    # 剩余天数
    status_response = make_request(STATUS_URL, 'GET', HEADERS_TEMPLATE, cookies=cookie)
    try:
        status_data = status_response.json() if status_response else {}
        remaining_days = f"{int(float(status_data.get('data', {}).get('leftDays',0)))} 天"
    except:
        remaining_days = "获取失败"

    # 总积分
    points_response = make_request(POINTS_URL, 'GET', HEADERS_TEMPLATE, cookies=cookie)
    points_data = {}
    current_points_numeric = 0
    try:
        points_data = points_response.json() if points_response else {}
        current_points_numeric = int(float(points_data.get('points', 0)))
        remaining_points = f"{current_points_numeric} 积分"
    except:
        remaining_points = "获取失败"

    # 自动兑换
    required_points = EXCHANGE_POINTS.get(exchange_plan, 500)
    if current_points_numeric >= required_points:
        exchange_response = make_request(EXCHANGE_URL, 'POST', HEADERS_TEMPLATE, {"planType": exchange_plan}, cookies=cookie)
        try:
            exchange_data = exchange_response.json() if exchange_response else {}
            code = exchange_data.get('code', -1)
            exchange_msg = f"兑换成功：{exchange_plan}" if code==0 else f"兑换失败：{exchange_plan} 代码:{code}"
        except:
            exchange_msg = f"兑换响应解析失败：{exchange_plan}"
    else:
        exchange_msg = f"积分不足，未兑换：{exchange_plan}"

    return status_msg, points_gained, remaining_days, remaining_points, exchange_msg

# ---------------------- 格式化推送 ----------------------
def format_push_content(results: List[Dict[str,str]]) -> Tuple[str,str]:
    success_count = sum(1 for r in results if "成功" in r['status'])
    fail_count = sum(1 for r in results if "失败" in r['status'] or "失败" in r['exchange'])
    repeat_count = sum(1 for r in results if "重复" in r['status'])

    title = f'GLaDOS 签到, 成功{success_count}, 失败{fail_count}, 重复{repeat_count}'
    content_lines = []
    for i, r in enumerate(results,1):
        line = f"账号{i}: P:{r['points']} 剩余天数:{r['days']} 总积分:{r['points_total']} | {r['status']}; {r['exchange']}"
        content_lines.append(line)
    return title, "\n".join(content_lines)

# ---------------------- Telegram 推送 ----------------------
def send_telegram(title:str, content:str, bot_token:str, chat_id:str):
    if not bot_token or not chat_id:
        logger.info("未配置 Telegram，跳过 TG 推送。")
        return
    message = f"*{title}*\n```\n{content}\n```"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        resp.raise_for_status()
        logger.info("Telegram 推送成功")
    except Exception as e:
        logger.error(f"Telegram 推送失败: {e}")

# ---------------------- 主函数 ----------------------
def main():
    push_key, cookies_list, exchange_plan, tg_token, tg_chat_id = load_config()
    results = []

    for idx, cookie in enumerate(cookies_list,1):
        logger.info(f"处理账号 {idx}...")
        status, points, days, points_total, exchange = checkin_and_process(cookie, exchange_plan)
        results.append({
            'status': status,
            'points': points,
            'days': days,
            'points_total': points_total,
            'exchange': exchange
        })

    title, content = format_push_content(results)
    logger.info(f"推送标题: {title}")
    logger.info(f"推送内容:\n{content}")

    # PushDeer
    if push_key:
        try:
            pushdeer = PushDeer(pushkey=push_key)
            pushdeer.send_text(title, desp=content)
            logger.info("PushDeer 推送成功")
        except Exception as e:
            logger.error(f"PushDeer 推送失败: {e}")

    # Telegram
    send_telegram(title, content, tg_token, tg_chat_id)

if __name__ == "__main__":
    main()
