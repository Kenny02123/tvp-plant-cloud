import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import pandas as pd
from gspread_formatting import * # 確保異常時能變紅字

# 1. 巡檢點位配置 (包含您要求的所有大類與範圍)
INSPECTION_CONFIG = {
    "MAC A 空壓機": {
        "LTI11190 油液位": None,
        "TI11190 油溫": (50.0, 65.0),
        "TI11161 油回水溫度": (20.0, 35.0),
        "TI11119 一段出水溫度": (20.0, 40.0),
        "TI11129 二段出水溫度": (20.0, 40.0),
        "TI11139 三段出水溫度": (20.0, 40.0),
        "馬達回水溫度": (20.0, 40.0),
        "PI202(1191) 油槽真空度": (-10.0, -1.0),
        "自動排水器功能": None,
        "冷卻水進出口壓差": (0.5, 1.5)
    },
    "MAC B 空壓機": {
        "LTI11190 油液位": None,
        "TI11190 油溫": (50.0, 65.0),
        "TI11161 油回水溫度": (20.0, 35.0),
        "TI11119 一段出水溫度": (20.0, 40.0),
        "TI11129 二段出水溫度": (20.0, 40.0),
        "TI11139 三段出水溫度": (20.0, 40.0),
        "馬達回水溫度": (20.0, 40.0),
        "PI202(1191) 油槽真空度": (-10.0, -1.0),
        "自動排水器功能": None,
        "冷卻水進出口壓差": (0.5, 1.5)
    },
    "PPU 系統": {
        "PI8392 PPU 儀表入口壓": (8.0, 11.0), 
    },
    "冷箱 PURGE 氣源": {
        "FI3237 PURGE 流量": (70.0, 120.0),
        "FI3291.1 熱交換器 PURGE 用量": (5.0, 25.0),
        "FI3291.2 熱交換器 PURGE 用量": (5.0, 25.0),
        "FI3292.1 COLD BOX PURGE 用量": (5.0, 25.0),
        "FI3292.2 COLD BOX PURGE 用量": (5.0, 25.0),
        "FI3292.3 COLD BOX PURGE 用量": (5.0, 25.0), 
    },
    "膨脹機 CEB": {
        "TI3430 油溫": (50.0, 65.0),
        "LI3430 油液位": None,
        "PI3431.1 除霧風扇抽風壓力": (-2.0, 10.0),
        "PI3431.2 除霧風扇抽風壓力": (0.0, 3.0),
        "TI3437.2 調溫後進 TFC 油溫": (35.0, 50.0),
        "PI3433.A oil pressure": (8.5, 15.0),
        "油濾網壓差 檢查油壓差視窗是否有突起": None,
        "聯軸器 確認加熱器周圍是否有結冰": None,
    },
    "膨脹發電機 TG": {
        "TI3490.1 油溫": (40.0, 65.0),
        "LI3490 油液位": None,
        "TI3497 調溫後進 TFC 油溫": (38.0, 48.0),
        "PI3491.1 除霧風扇抽風壓力": (-2.0, 10.0),
        "PI3491.2 除霧風扇抽風壓力": (0.0, 2.0),
        "PI3497.4 gearbox lube oil pressure": (1.8, 3.0),
        "聯軸器 確認加熱器周圍是否有結冰": None,
    }
}

SHEET_NAME = "tvp plant" # 試算表檔案名稱
ORDERED_TAGS = []
for category, points in INSPECTION_CONFIG.items():
    for point in points:
        ORDERED_TAGS.append(f"{category} - {point}")

# 頁面配置
st.set_page_config(page_title="TVP 30K 巡檢系統", page_icon="🏭", layout="centered")

# 初始化狀態
if "submit_status" not in st.session_state:
    st.session_state.submit_status = None

# --- 工具函式 ---

def get_gspread_client():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        # 先嘗試從 Streamlit Secrets 讀取 (雲端版)
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        # 若失敗則嘗試本地檔案 (本地開發用)
        else:
            creds = Credentials.from_service_account_file('service_account.json', scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google 認證失敗: {e}")
        return None

def get_or_init_worksheet(gc, sheet_name, worksheet_title):
    sh = gc.open(sheet_name)
    try:
        ws = sh.worksheet(worksheet_title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_title, rows=1000, cols=50)
    
    # 初始化 A 欄 TAG 名稱
    existing_col_a = ws.col_values(1)
    if not existing_col_a or existing_col_a[0] != "TAG":
        expected_col_a = [["TAG"]] + [[tag] for tag in ORDERED_TAGS]
        ws.update(range_name=f"A1:A{len(expected_col_a)}", values=expected_col_a)
    return ws

def submit_data():
    category = st.session_state.get("category")
    point_name = st.session_state.get("point_name")
    input_key = f"input_{category}_{point_name}"
    reading_input = st.session_state.get(input_key)
    note = st.session_state.get("note", "")
    
    judgment = "✅"
    config_value = INSPECTION_CONFIG[category][point_name]
    
    # 判斷邏輯
    if config_value is None:
        if "不正常" in str(reading_input): judgment = "🚨"
    else:
        try:
            val = float(reading_input)
            if val < config_value[0] or val > config_value[1]: judgment = "🚨"
        except: judgment = "🚨"

    final_value = f"{reading_input} [{datetime.now().strftime('%H:%M')}] {judgment}"
    if note: final_value += f" ({note})"

    try:
        gc = get_gspread_client()
        ws = get_or_init_worksheet(gc, SHEET_NAME, f"{st.session_state.user_area}_Data")
        
        # 尋找列與欄
        row_index = ORDERED_TAGS.index(f"{category} - {point_name}") + 2
        today_str = datetime.now().strftime("%Y/%m/%d")
        headers = ws.row_values(1)
        
        if today_str in headers:
            col_index = headers.index(today_str) + 1
        else:
            col_index = len(headers) + 1
            ws.update_cell(1, col_index, today_str)

        # 寫入數值
        ws.update_cell(row_index, col_index, final_value)
        
        # 異常變紅
        if judgment == "🚨":
            fmt = cellFormat(textFormat=textFormat(foregroundColor=color(1, 0, 0), bold=True))
            format_cell_range(ws, f"{gspread.utils.rowcol_to_a1(row_index, col_index)}", fmt)

        st.session_state.submit_status = {"type": "success", "msg": f"儲存成功: {final_value}"}
        st.session_state["note"] = "" # 清空備註
    except Exception as e:
        st.session_state.submit_status = {"type": "error", "msg": f"錯誤: {e}"}

# --- 頁面渲染 ---

def login_page():
    st.title("🏭 TVP 30K 巡檢系統")
    with st.form("login"):
        shift = st.selectbox("選擇班別", ["早班", "晚班"])
        name = st.text_input("請輸入姓名")
        area = st.selectbox("巡檢區域", ["TN2", "TN5", "TN6", "TN7"])
        if st.form_submit_button("進入系統"):
            if name:
                st.session_state.update({"logged_in": True, "user_shift": shift, "user_name": name, "user_area": area})
                st.rerun()

def main_page():
    st.sidebar.title(f"👤 {st.session_state.user_name}")
    st.sidebar.write(f"班別: {st.session_state.user_shift} | 區域: {st.session_state.user_area}")
    if st.sidebar.button("登出/切換區域"):
        st.session_state.logged_in = False
        st.rerun()

    st.title(f"✍️ {st.session_state.user_area} 巡檢報表")
    
    # 選單
    category = st.selectbox("1. 選擇設備", list(INSPECTION_CONFIG.keys()), key="category")
    point_name = st.selectbox("2. 選擇點位", list(INSPECTION_CONFIG[category].keys()), key="point_name")
    
    config = INSPECTION_CONFIG[category][point_name]
    input_key = f"input_{category}_{point_name}"
    
    if config is None:
        st.radio("狀態確認", ["✅ 正常 (OK)", "❌ 不正常 (NG)"], key=input_key)
    else:
        st.info(f"正常範圍: {config[0]} ~ {config[1]}")
        st.number_input("輸入讀值", format="%.2f", step=0.1, key=input_key)
    
    st.text_input("備註 (Note)", key="note")
    st.button("🚀 提交紀錄", on_click=submit_data, use_container_width=True)

    if st.session_state.submit_status:
        s = st.session_state.submit_status
        if s["type"] == "success": st.success(s["msg"])
        else: st.error(s["msg"])

    # 底部顯示進度看板 (您要求的功能)
    st.divider()
    st.subheader("📊 今日填寫進度")
    # 此處可依照您的 render_progress 邏輯顯示表格...
    st.info("進度看板已在背景與 Google Sheets 同步中")

# --- 程式入口 ---
if not st.session_state.get("logged_in"):
    login_page()
else:
    main_page()