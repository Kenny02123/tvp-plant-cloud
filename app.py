import streamlit as st
import gspread
from datetime import datetime
import os
import pandas as pd
import time
import json

# 1. Configuration
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

SHEET_NAME = "tvp plant"

# Flatten config for easy lookup and ordering
ORDERED_TAGS = []
for category, points in INSPECTION_CONFIG.items():
    for point in points:
        ORDERED_TAGS.append(f"{category} - {point}")

# Page configuration - Mobile First
st.set_page_config(page_title="TVP 30K 巡檢系統", page_icon="🏭", layout="centered")

# Initialize session state
if "submit_status" not in st.session_state:
    st.session_state.submit_status = None

# --- Helper Functions ---

def get_gspread_client():
    # Priority 1: Streamlit Secrets
    if "gcp_service_account" in st.secrets:
        try:
            # st.secrets returns a AttrDict, we need a standard dict for gspread
            creds_dict = dict(st.secrets["gcp_service_account"])
            return gspread.service_account_from_dict(creds_dict)
        except Exception as e:
            st.error(f"Secrets 讀取失敗: {e}")
            return None
            
    # Priority 2: Local File
    if os.path.exists("service_account.json"):
        return gspread.service_account(filename='service_account.json')
        
    st.error("找不到認證金鑰 (service_account.json 或 st.secrets)")
    return None

def get_or_init_worksheet(gc, sheet_name, worksheet_title):
    try:
        sh = gc.open(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"找不到試算表: {sheet_name}")
        raise

    try:
        ws = sh.worksheet(worksheet_title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_title, rows=1000, cols=50)
    
    # Check and Initialize Column A (TAGs)
    existing_col_a = ws.col_values(1)
    expected_col_a = ["TAG"] + ORDERED_TAGS
    
    # If Column A is empty or doesn't match, we update it.
    if len(existing_col_a) < len(expected_col_a) or existing_col_a[:len(expected_col_a)] != expected_col_a:
        cell_list = [[tag] for tag in expected_col_a]
        ws.update(range_name=f"A1:A{len(expected_col_a)}", values=cell_list)
        
    return ws

def submit_data():
    # Retrieve values
    shift = st.session_state.get("user_shift", "")
    employee_name = st.session_state.get("user_name", "")
    area = st.session_state.get("user_area", "")
    
    category = st.session_state.get("category", "")
    point_name = st.session_state.get("point_name", "")
    note = st.session_state.get("note", "")
    
    input_key = f"input_{category}_{point_name}"
    
    if input_key not in st.session_state:
        st.session_state.submit_status = {"type": "error", "msg": "找不到輸入數值，請重新操作。"}
        return
        
    reading_input = st.session_state[input_key]
    
    # Determine config and judgment
    config_value = INSPECTION_CONFIG[category][point_name]
    judgment = "✅"
    reading_to_save = str(reading_input)
    
    if config_value is None:
        if "不正常" in str(reading_input):
            judgment = "🚨"
            reading_to_save = "NG"
        else:
            reading_to_save = "OK"
    else:
        min_val, max_val = config_value
        if float(reading_input) < min_val or float(reading_input) > max_val:
            judgment = "🚨"
            
    # Format value for cell: "Value [HH:MM]"
    current_time_short = datetime.now().strftime("%H:%M")
    final_value = f"{reading_to_save} [{current_time_short}]"
    
    if judgment == "🚨":
        final_value += " 🚨"
    
    if note:
        final_value += f" ({note})"
            
    try:
        gc = get_gspread_client()
        if not gc: return

        worksheet_title = f"{area}_Data"
        ws = get_or_init_worksheet(gc, SHEET_NAME, worksheet_title)
        
        # 1. Find Row Index for TAG
        full_tag = f"{category} - {point_name}"
        try:
            row_index = ORDERED_TAGS.index(full_tag) + 2 
        except ValueError:
            st.session_state.submit_status = {"type": "error", "msg": f"找不到 TAG: {full_tag}"}
            return

        # 2. Find Column Index for Date
        today_str = datetime.now().strftime("%Y/%m/%d")
        header_row = ws.row_values(1)
        
        if today_str in header_row:
            col_index = header_row.index(today_str) + 1
        else:
            # Add new date column
            col_index = len(header_row) + 1
            ws.update_cell(1, col_index, today_str)
            
        # 3. Update Cell
        ws.update_cell(row_index, col_index, final_value)
        
        st.session_state.submit_status = {
            "type": "success", 
            "msg": f"資料已儲存！\n點位: {point_name}\n數值: {final_value}"
        }
        
        # Reset input
        if config_value is None:
            st.session_state[input_key] = "✅ 正常 (OK)"
        else:
            st.session_state[input_key] = 0.0
        st.session_state["note"] = ""
            
    except Exception as e:
        st.session_state.submit_status = {"type": "error", "msg": f"發生錯誤: {e}"}

def switch_area():
    st.session_state["user_area"] = None
    st.rerun()

def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# --- Pages ---

def login_page():
    st.title("TVP 30K 巡檢系統 - 登入")
    with st.form("login_form"):
        shift = st.selectbox("選擇班別", ["早班", "晚班"])
        name = st.text_input("請輸入姓名")
        area = st.selectbox("選擇巡檢區域", ["TN2", "TN5", "TN6", "TN7"])
        submitted = st.form_submit_button("進入巡檢")
        if submitted:
            if name:
                st.session_state["logged_in"] = True
                st.session_state["user_shift"] = shift
                st.session_state["user_name"] = name
                st.session_state["user_area"] = area
                st.rerun()
            else:
                st.error("請輸入姓名")

def area_selection_page():
    st.title("請選擇巡檢區域")
    col1, col2, col3, col4 = st.columns(4)
    if col1.button("TN2"):
        st.session_state["user_area"] = "TN2"
        st.rerun()
    if col2.button("TN5"):
        st.session_state["user_area"] = "TN5"
        st.rerun()
    if col3.button("TN6"):
        st.session_state["user_area"] = "TN6"
        st.rerun()
    if col4.button("TN7"):
        st.session_state["user_area"] = "TN7"
        st.rerun()
    if st.button("登出"):
        logout()

def render_progress(area):
    st.subheader(f"📊 今日待辦清單 ({area})")
    try:
        gc = get_gspread_client()
        if not gc: return

        worksheet_title = f"{area}_Data"
        ws = get_or_init_worksheet(gc, SHEET_NAME, worksheet_title)
        
        data = ws.get_all_values()
        today_str = datetime.now().strftime("%Y/%m/%d")
        headers = data[0]
        
        if today_str not in headers:
            st.warning("今日尚未開始巡檢")
            return

        col_index = headers.index(today_str)
        
        progress_data = []
        
        # Create a map of TAG -> Value from the sheet
        sheet_map = {}
        for row in data[1:]:
            if len(row) > 0:
                tag = row[0]
                val = row[col_index] if col_index < len(row) else ""
                sheet_map[tag] = val
        
        for tag in ORDERED_TAGS:
            val = sheet_map.get(tag, "")
            status = "✅ 完成" if val else "❌ 未填"
            progress_data.append({"TAG": tag, "數值": val, "狀態": status})
        
        df = pd.DataFrame(progress_data)
        
        def highlight_missing(row):
            return ['background-color: #ffcccc' if row['狀態'] == "❌ 未填" else '' for _ in row]

        st.dataframe(df.style.apply(highlight_missing, axis=1))
        
        completed = len([x for x in progress_data if x["狀態"] == "✅ 完成"])
        total = len(progress_data)
        if total > 0:
            st.progress(completed / total)
            st.write(f"完成度: {completed}/{total}")
            
    except Exception as e:
        st.error(f"讀取進度失敗: {e}")

def main_inspection_page():
    area = st.session_state.user_area
    
    # Sidebar
    st.sidebar.title("巡檢資訊")
    st.sidebar.info(f"班別: {st.session_state.user_shift}")
    st.sidebar.info(f"姓名: {st.session_state.user_name}")
    st.sidebar.info(f"區域: {area}")
    
    if st.sidebar.button("🏠 返回區域選擇"):
        switch_area()
    if st.sidebar.button("更換班別/登出"):
        logout()

    # Routing
    if area == "TN2":
        st.title(f"TVP Plant 設備巡檢 ({area})")
        st.info("TN2 專屬頁面建置中...")
        render_progress(area)
    elif area in ["TN5", "TN6", "TN7"]:
        render_standard_inspection_page(area)
    else:
        st.error("未知的區域")

def render_standard_inspection_page(area):
    st.title(f"TVP Plant 設備巡檢 ({area})")

    # Inputs
    categories = list(INSPECTION_CONFIG.keys())
    category = st.selectbox("設備大類", categories, key="category")

    points = list(INSPECTION_CONFIG[category].keys())
    point_name = st.selectbox("點位名稱", points, key="point_name")

    config_value = INSPECTION_CONFIG[category][point_name]
    input_key = f"input_{category}_{point_name}"

    if config_value is None:
        status_options = ["✅ 正常 (OK)", "❌ 不正常 (NG)"]
        if input_key not in st.session_state:
            st.session_state[input_key] = status_options[0]
        st.radio("狀態確認", status_options, key=input_key)
    else:
        min_val, max_val = config_value
        st.info(f"正常範圍: {min_val} ~ {max_val}")
        if input_key not in st.session_state:
            st.session_state[input_key] = 0.0
        # Mobile Optimization: format="%.2f" triggers numeric keyboard
        st.number_input("讀值輸入", step=0.1, format="%.2f", key=input_key)

    st.text_input("備註 (Note)", key="note")
    st.button("送出 (Submit)", on_click=submit_data)

    if st.session_state.submit_status:
        status = st.session_state.submit_status
        if status["type"] == "success":
            st.success(status["msg"])
        else:
            st.error(status["msg"])

    st.markdown("---")
    render_progress(area)

# --- Main Entry ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    login_page()
else:
    if "user_area" not in st.session_state or st.session_state["user_area"] is None:
        area_selection_page()
    else:
        main_inspection_page()
