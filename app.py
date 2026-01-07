import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pandas as pd
from gspread_formatting import *
import time

# --- 1. 巡檢點位配置 ---
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
    st.session_state.selected_category = list(INSPECTION_CONFIG.keys())[0]

# --- 工具函式 ---

def get_gspread_client():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
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
    category = st.session_state.get("category_selector") # 使用 key 獲取
    point_name = st.session_state.get("point_selector")
    
    # 根據點位類型獲取輸入
    config_value = INSPECTION_CONFIG[category][point_name]
    input_key = f"input_{category}_{point_name}"
    
    if config_value is None:
        reading_input = st.session_state.get(input_key)
    else:
        reading_input = st.session_state.get(input_key)

    note = st.session_state.get("note", "")
    
    judgment = "✅"
    
    # 判斷邏輯
    if config_value is None:
        if "不正常" in str(reading_input): judgment = "🚨"
    else:
        try:
            val = float(reading_input)
            if val < config_value[0] or val > config_value[1]: judgment = "🚨"
        except: judgment = "🚨"

    # 格式：讀值 [時間] 判定 / 姓名
    current_time = datetime.now().strftime('%H:%M')
    user_name = st.session_state.user_name
    final_value = f"{reading_input} [{current_time}] {judgment} / {user_name}"
    
    if note: final_value += f" ({note})"

    try:
        gc = get_gspread_client()
        ws = get_or_init_worksheet(gc, SHEET_NAME, f"{st.session_state.user_area}_Data")
        
        # 尋找列與欄
        full_tag = f"{category} - {point_name}"
        if full_tag in ORDERED_TAGS:
            row_index = ORDERED_TAGS.index(full_tag) + 2
        else:
            st.error("找不到點位對應的行")
            return

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
            try:
                fmt = cellFormat(
                    backgroundColor=color(1, 0.8, 0.8), # 淺紅色背景
                    textFormat=textFormat(foregroundColor=color(1, 0, 0), bold=True) # 紅色粗體字
                )
                format_cell_range(ws, f"{gspread.utils.rowcol_to_a1(row_index, col_index)}", fmt)
            except Exception as fmt_err:
                print(f"Format error: {fmt_err}")

        st.session_state.submit_status = {"type": "success", "msg": f"儲存成功: {final_value}"}
        st.session_state["note"] = "" # 清空備註
        
    except Exception as e:
        st.session_state.submit_status = {"type": "error", "msg": f"錯誤: {e}"}

def clear_record():
    tag_to_clear = st.session_state.get("tag_to_clear")
    if not tag_to_clear: return

    try:
        gc = get_gspread_client()
        ws = get_or_init_worksheet(gc, SHEET_NAME, f"{st.session_state.user_area}_Data")
        
        row_index = ORDERED_TAGS.index(tag_to_clear) + 2
        today_str = datetime.now().strftime("%Y/%m/%d")
        headers = ws.row_values(1)
        
        if today_str in headers:
            col_index = headers.index(today_str) + 1
            ws.update_cell(row_index, col_index, "") # 清空
            st.success(f"已清除紀錄: {tag_to_clear}")
            time.sleep(1)
            st.rerun()
        else:
            st.warning("今日尚無欄位可清除")
            
    except Exception as e:
        st.error(f"清除失敗: {e}")

# --- 顯示進度與修正功能 ---
def render_progress(area):
    st.subheader(f"📊 今日待辦清單 ({area})")
    try:
        gc = get_gspread_client()
        if not gc: return
        
        sh = gc.open(SHEET_NAME)
        worksheet_title = f"{area}_Data"
        try:
            ws = sh.worksheet(worksheet_title)
        except:
            st.info("尚無資料表")
            return
        
        all_data = ws.get_all_values()
        today_str = datetime.now().strftime("%Y/%m/%d")
        
        if not all_data:
            st.info("資料表為空")
            return

        headers = all_data[0]
        
        if today_str not in headers:
            st.warning("📅 今日巡檢尚未開始，請提交第一筆數據。")
            return

        col_idx = headers.index(today_str)
        progress_data = []
        filled_tags = [] # 用於修正選單
        
        # 建立 Map: TAG -> Value
        sheet_map = {}
        for row in all_data[1:]:
            if len(row) > col_idx:
                val = row[col_idx]
                sheet_map[row[0]] = val
                if val: filled_tags.append(row[0])
            else:
                sheet_map[row[0]] = ""
        
        # 產生進度列表
        for cat, pts in INSPECTION_CONFIG.items():
            for pt in pts:
                tag = f"{cat} - {pt}"
                val = sheet_map.get(tag, "")
                status = "✅ 完成" if val else "❌ 未填"
                progress_data.append({"點位": tag, "數值": val, "狀態": status})
        
        df = pd.DataFrame(progress_data)
        
        # 美化表格
        def highlight_missing(s):
            return ['background-color: #ffcccc' if s.狀態 == "❌ 未填" else '' for _ in s]

        st.dataframe(df.style.apply(highlight_missing, axis=1), use_container_width=True)
        
        # 進度條
        done = len([x for x in progress_data if x["狀態"] == "✅ 完成"])
        total = len(progress_data)
        if total > 0:
            st.progress(done / total)
            st.write(f"📈 完成度：{done} / {total}")

        st.divider()
        st.subheader("🛠️ 填錯修正")
        if filled_tags:
            st.selectbox("選擇要清除的紀錄", filled_tags, key="tag_to_clear")
            st.button("🗑️ 清除紀錄", on_click=clear_record, type="primary")
        else:
            st.info("今日尚無可清除的紀錄")
            
    except Exception as e:
        st.info(f"同步進度中... ({e})")

# --- 側邊欄導航 ---
def sidebar_nav():
    st.sidebar.title(f"👤 {st.session_state.user_name}")
    st.sidebar.info(f"班別: {st.session_state.user_shift} | 區域: {st.session_state.user_area}")
    
    st.sidebar.divider()
    
    # 區域切換
    if st.sidebar.button("📍 切換區域", use_container_width=True):
        st.rerun()

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
    sidebar_nav() # 載入側邊欄

    st.title(f"✍️ {st.session_state.user_area} 巡檢報表")
    
    # 確保 selected_category 在選項中
    categories = list(INSPECTION_CONFIG.keys())
    try:
        cat_index = categories.index(st.session_state.selected_category)
    except:
        cat_index = 0
        
    # 1. 選擇設備 (連動 Sidebar)
    category = st.selectbox("1. 選擇設備", categories, index=cat_index, key="category_selector")
    # 更新 session state 以保持同步
    st.session_state.selected_category = category
    
    # 2. 選擇點位
    points = list(INSPECTION_CONFIG[category].keys())
    point_name = st.selectbox("2. 選擇點位", points, key="point_selector")
    
    # 3. 輸入數值
    config = INSPECTION_CONFIG[category][point_name]
    input_key = f"input_{category}_{point_name}"
    
    if config is None:
        st.radio("狀態確認", ["✅ 正常 (OK)", "❌ 不正常 (NG)"], key=input_key, horizontal=True)
    else:
        st.info(f"正常範圍: {config[0]} ~ {config[1]}")
        st.number_input("輸入讀值", format="%.2f", step=0.1, key=input_key)
    
    st.text_input("備註 (Note)", key="note")
    st.button("🚀 提交紀錄", on_click=submit_data, use_container_width=True)

    if st.session_state.submit_status:
        s = st.session_state.submit_status
        if s["type"] == "success": st.success(s["msg"])
        else: st.error(s["msg"])

    st.divider()
    render_progress(st.session_state.user_area)

# --- 程式入口 ---
if not st.session_state.get("logged_in"):
    login_page()
elif st.session_state.get("user_area") is None:
    # 處理切換區域後的狀態
    st.session_state.user_area = None # 確保是 None
    # 顯示簡易區域選擇或直接回登入頁？
    # 這裡簡單處理：若已登入但無區域，顯示區域選擇
    st.title("📍 請選擇巡檢區域")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("TN5", use_container_width=True):
            st.session_state.user_area = "TN5"
            st.rerun()
        if st.button("TN6", use_container_width=True):
            st.session_state.user_area = "TN6"
            st.rerun()
    with col2:
        if st.button("TN7", use_container_width=True):
            st.session_state.user_area = "TN7"
            st.rerun()
        if st.button("TN2", use_container_width=True):
            st.session_state.user_area = "TN2"
            st.rerun()
else:
    main_page()