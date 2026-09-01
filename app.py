import streamlit as st
from curl_cffi import requests
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Seair Seaplanes 機位查詢",
    page_icon="🛥️",
    layout="wide"
)

st.title("🛥️ Seair Seaplanes 機位查詢")
st.caption("查詢水上飛機航班空缺及價位 — seairseaplanes.com")

# ── 常數 ─────────────────────────────────────────────────
API_BASE = "https://www.seairseaplanes.com/booking/api/"

LOCATIONS = {
    "Vancouver Harbour": 10,
    "Victoria Harbour": 11,
    "Nanaimo": 5,
    "Richmond (YVR)": 7,
    "Ganges Harbour": 1,
}

IATA = {
    "Vancouver Harbour": "CXH",
    "Victoria Harbour": "YWH",
    "Nanaimo": "ZNA",
    "Richmond (YVR)": "YVR",
    "Ganges Harbour": "GNG",
}

ROUTES = [
    ("Vancouver Harbour", "Victoria Harbour"),
    ("Victoria Harbour", "Vancouver Harbour"),
    ("Nanaimo", "Richmond (YVR)"),
    ("Richmond (YVR)", "Nanaimo"),
    ("Nanaimo", "Vancouver Harbour"),
    ("Vancouver Harbour", "Nanaimo"),
    ("Richmond (YVR)", "Ganges Harbour"),
    ("Ganges Harbour", "Richmond (YVR)"),
    ("Ganges Harbour", "Vancouver Harbour"),
    ("Vancouver Harbour", "Ganges Harbour"),
]

FARE_LABELS = {
    "premium":    "Premium",
    "standard":   "Classic",
    "super_saver": "Essential",
    "last_min":   "Saver",
}

HEADERS = {
    "Referer": "https://www.seairseaplanes.com/book-now/book-a-flight",
}

BOOKING_PAGE_URL = "https://www.seairseaplanes.com/book-now/book-a-flight"


@st.cache_resource(ttl=1800)
def get_session() -> requests.Session:
    """建立 session（模擬 Chrome TLS 指紋）並訪問訂票頁面取得 Incapsula 驗證 cookie，讓後續 API 請求能通過反機械人檢查"""
    session = requests.Session(impersonate="chrome")
    session.headers.update(HEADERS)
    session.get(BOOKING_PAGE_URL, timeout=15)
    return session


# ── API 函數 ──────────────────────────────────────────────
def fetch_flights(start_loc: int, end_loc: int, date_str: str,
                  adults: int, children: int, infants: int) -> list[dict]:
    """呼叫 Seair API 取得指定日期的航班列表"""
    params = {
        "dir": "D",
        "flight_type": "departing",
        "date": date_str,
        "dep_date": date_str,
        "start_loc": str(start_loc),
        "end_loc": str(end_loc),
        "pax_a": str(adults),
        "pax_c": str(children),
        "pax_i": str(infants),
        "action": "flight_search",
    }
    r = get_session().get(API_BASE, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_lowest_prices(start_loc: int, end_loc: int, start_date: str,
                        adults: int, children: int, infants: int,
                        days: int = 14) -> dict:
    """取得未來 N 天每天的最低票價"""
    params = {
        "action": "flight_day_lowest",
        "days": str(days),
        "date": start_date,
        "pax_a": str(adults),
        "pax_c": str(children),
        "pax_i": str(infants),
        "dir": "D",
        "start_loc": str(start_loc),
        "end_loc": str(end_loc),
    }
    r = get_session().get(API_BASE, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


# ── 資料解析 ──────────────────────────────────────────────
def parse_flights_to_df(raw: list[dict], departure_name: str, arrival_name: str, date_str: str) -> pd.DataFrame:
    """將 API 回傳的航班資料轉為 DataFrame"""
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        info = item.get("flight_info", {})
        fares_avail = item.get("fares_available", [])
        all_fares = item.get("all_fares", [])

        # 起飛時間
        f_start = info.get("f_start", "")
        try:
            dt = datetime.strptime(f_start, "%Y-%m-%d %H:%M:%S")
            dep_time = dt.strftime("%H:%M")
        except Exception:
            dep_time = f_start

        fee_total = info.get("f_fee_total", 0)

        route = f"{IATA[departure_name]}/{IATA[arrival_name]}"

        # 整理每個艙等
        for fare in fares_avail + all_fares:
            seats = fare.get("seats_av", 0)
            adult_price = float(fare.get("adult", 0))
            rows.append({
                "Route": route,
                "Date": date_str,
                "Departure": dep_time,
                "Class": fare.get("label", fare.get("fare_type", "")),
                "Seats": seats,
                "Price": f"${adult_price:.2f}",
                "_seats_av": seats,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Departure", "_seats_av"], ascending=[True, False])
        df = df.drop(columns=["_seats_av"])
    return df


def style_seats(val) -> str:
    try:
        n = int(val)
        if n == 0:
            return "color: #dc3545; font-weight: bold"
        if n <= 2:
            return "color: #fd7e14; font-weight: bold"
        return "color: #28a745; font-weight: bold"
    except Exception:
        return ""


# ── Sidebar ──────────────────────────────────────────────
with st.sidebar:
    st.header("查詢條件")

    st.subheader("航線")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("全選", use_container_width=True):
            for dep, arr in ROUTES:
                st.session_state[f"route_{dep}_{arr}"] = True
    with col_b:
        if st.button("清除", use_container_width=True):
            for dep, arr in ROUTES:
                st.session_state[f"route_{dep}_{arr}"] = False

    selected_routes = []
    for dep, arr in ROUTES:
        key = f"route_{dep}_{arr}"
        checked = st.checkbox(f"{IATA[dep]}/{IATA[arr]}", key=key)
        if checked:
            selected_routes.append((dep, arr))

    min_date = datetime.today().date()
    travel_date = st.date_input(
        "出發日期",
        value=min_date + timedelta(days=1),
        min_value=min_date,
        max_value=min_date + timedelta(days=365),
    )

    st.divider()
    st.subheader("乘客人數")
    adults = st.number_input("成人 (12歲以上)", min_value=1, max_value=9, value=1)
    children = st.number_input("小童 (2–11歲)", min_value=0, max_value=9, value=0)
    infants = st.number_input("嬰兒 (0–23個月)", min_value=0, max_value=int(adults), value=0)

    st.divider()
    show_calendar = st.toggle("顯示14日最低價日曆", value=True)
    search_btn = st.button("🔍 查詢航班", use_container_width=True, type="primary")


# ── Main Area ─────────────────────────────────────────────
end_display = (travel_date + timedelta(days=6)).strftime('%Y-%m-%d')
st.caption(f"查詢範圍：{travel_date.strftime('%Y-%m-%d')} 至 {end_display}（連續7天）")
st.divider()

if search_btn:
    if not selected_routes:
        st.warning("請至少選擇一條航線。")
    else:
        date_str = travel_date.strftime("%Y-%m-%d")
        a, c, i = int(adults), int(children), int(infants)
        all_dfs = []
        search_dates = [travel_date + timedelta(days=d) for d in range(7)]

        for departure_name, arrival_name in selected_routes:
            start_id = LOCATIONS[departure_name]
            end_id = LOCATIONS[arrival_name]

            with st.spinner(f"搜尋 {IATA[departure_name]}/{IATA[arrival_name]} (7天) ..."):
                for day in search_dates:
                    day_str = day.strftime("%Y-%m-%d")
                    try:
                        raw = fetch_flights(start_id, end_id, day_str, a, c, i)
                        if raw and isinstance(raw, list):
                            df = parse_flights_to_df(raw, departure_name, arrival_name, day_str)
                            all_dfs.append(df)
                    except Exception as e:
                        st.error(f"{IATA[departure_name]}/{IATA[arrival_name]} ({day_str}): {e}")

        if all_dfs:
            combined = pd.concat(all_dfs, ignore_index=True)
            end_date_str = (travel_date + timedelta(days=6)).strftime("%Y-%m-%d")
            st.subheader(f"✈️ {len(combined)} 個航班（{date_str} 至 {end_date_str}）")
            st.dataframe(
                combined.style.map(style_seats, subset=["Seats"]),
                use_container_width=True,
                hide_index=True,
            )
            csv = combined.to_csv(index=False, encoding="utf-8-sig")
            st.download_button("📥 Download CSV", data=csv, file_name=f"seair_{date_str}_7days.csv", mime="text/csv")
        else:
            st.info(f"所選航線在 {date_str} 起7天內均沒有航班。")

else:
    st.info("請在左側勾選航線，然後點擊「查詢航班」按鈕。")

st.caption(f"資料來源：seairseaplanes.com | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
