import streamlit as st
import google.generativeai as genai
import pypdf
import json
import os
import urllib.request
from io import BytesIO

# --- Word (DOCX) 생성 라이브러리 예외 처리 ---
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# --- ReportLab PDF 라이브러리 연동 ---
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# --- 1. 페이지 기본 설정 ---
st.set_page_config(
    page_title="브니엘고 AI 생기부 정밀 평가 시스템",
    page_icon="🎓",
    layout="wide"
)

# --- 2. 로컬 채점 기준 보관 폴더 (영구 저장) ---
CRITERIA_DB_DIR = "criteria_database"
os.makedirs(CRITERIA_DB_DIR, exist_ok=True)

# --- 3. 헬퍼 함수 ---
def extract_text_from_pdf_stream(pdf_file):
    """RAM(메모리) 상에서 직접 PDF 텍스트 추출 및 정제 - 개인정보 휘발성 처리"""
    if pdf_file is None:
        return ""
    try:
        pdf_reader = pypdf.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            extracted = page.extract_text()
            if extracted:
                cleaned = extracted.replace("\r", "\n")
                text += cleaned + "\n"
        return text
    except Exception as e:
        st.error(f"PDF 텍스트 추출 중 오류: {e}")
        return ""

def load_local_file_text(filename):
    """저장된 채점 기준 파일 텍스트 로드"""
    path = os.path.join(CRITERIA_DB_DIR, filename)
    if not os.path.exists(path):
        return ""
    if filename.lower().endswith(".pdf"):
        try:
            reader = pypdf.PdfReader(path)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text
        except Exception:
            return ""
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="cp949") as f:
                    return f.read()
            except Exception:
                return ""

def get_korean_font_path():
    local_font_name = "NanumGothic.ttf"
    if os.path.exists(local_font_name):
        return local_font_name
    paths = [
        "C:\\Windows\\Fonts\\malgun.ttf",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    font_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    try:
        urllib.request.urlretrieve(font_url, local_font_name)
        if os.path.exists(local_font_name):
            return local_font_name
    except Exception:
        pass
    return None

# --- 세션 상태 초기화 (초기 미선택 고정) ---
if "feedback_main_cat" not in st.session_state:
    st.session_state["feedback_main_cat"] = "--- 피드백 대분류 선택 ---"

if "feedback_sub_cat" not in st.session_state:
    st.session_state["feedback_sub_cat"] = "--- 세부 영역 선택 ---"

# --- 4. 사이드바 구성 ---
st.sidebar.markdown("<h1 style='text-align: center;'>🎓</h1>", unsafe_allow_html=True)
st.sidebar.markdown("<h3 style='text-align: center;'>브니엘고 AI 평가 시스템</h3>", unsafe_allow_html=True)
st.sidebar.divider()

# 4-1. 입학사정관 선택
st.sidebar.markdown("### 🎯 1. 입학사정관 유형 선택")
evaluator_mode = st.sidebar.radio(
    "사정관 관점을 선택하세요.",
    ["인서울 입학사정관", "지거국 입학사정관"],
    index=0,
    key="evaluator_mode_radio"
)

st.sidebar.divider()

# 4-2. 피드백 버전 선택 (초기 미선택 상태 고정)
st.sidebar.markdown("### 📝 2. 평가 및 피드백 버전 선택")

def on_main_cat_change():
    st.session_state["feedback_sub_cat"] = "--- 세부 영역 선택 ---"
    if "eval_result" in st.session_state:
        del st.session_state["eval_result"]

feedback_category = st.sidebar.selectbox(
    "피드백 대분류를 선택하세요 (필수)",
    [
        "--- 피드백 대분류 선택 ---",
        "교사전용 피드백 버전",
        "학생용 피드백 버전"
    ],
    key="feedback_main_cat",
    on_change=on_main_cat_change
)

selected_feedback_type = "미선택"

if feedback_category == "교사전용 피드백 버전":
    selected_feedback_type = st.sidebar.radio(
        "세부 평가 영역 선택 (필수)",
        [
            "--- 세부 영역 선택 ---",
            "과목세부능력 특기사항 전용 피드백",
            "동아리 특기사항 전용 피드백",
            "생기부 종합 전용 피드백"
        ],
        key="feedback_sub_cat"
    )
elif feedback_category == "학생용 피드백 버전":
    selected_feedback_type = "학생전용 피드백"
    st.sidebar.info("🎓 학생 1인에 대한 냉정한 현위치 진단, 강점/약점 분석 및 앞으로의 탐구 솔루션을 제공합니다.")

st.sidebar.divider()

# 4-3. API 키 설정
api_key = ""
if os.path.exists("api_key.txt"):
    try:
        with open("api_key.txt", "r", encoding="utf-8") as f:
            api_key = f.read().strip()
    except Exception:
        pass

if not api_key and "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]

if not api_key:
    api_key = st.sidebar.text_input("🔑 구글 Gemini API Key 입력", type="password", key="api_key_input")
    if api_key:
        genai.configure(api_key=api_key)
        st.sidebar.success("✅ 인증 완료!")
else:
    genai.configure(api_key=api_key)
    st.sidebar.success("🔑 API 키 자동 인증 완료")

st.sidebar.divider()

# 4-4. 모델 선택
model_option = st.sidebar.selectbox(
    "🤖 Gemini AI 모델 선택",
    ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    index=0,
    key="model_option_select"
)

st.sidebar.divider()

# 4-5. 채점 기준 파일 관리
st.sidebar.markdown("### 📚 대학별 채점기준 DB (영구보관)")
uploaded_criteria = st.sidebar.file_uploader(
    "채점기준 PDF/TXT 업로드 (무제한)",
    type=["pdf", "txt"],
    accept_multiple_files=True,
    key="criteria_uploader"
)

if uploaded_criteria:
    for file in uploaded_criteria:
        dest_path = os.path.join(CRITERIA_DB_DIR, file.name)
        with open(dest_path, "wb") as f:
            f.write(file.getbuffer())
    st.sidebar.success(f"💾 {len(uploaded_criteria)}개 파일 DB 누적 저장 완료!")
    st.rerun()

accumulated_files = os.listdir(CRITERIA_DB_DIR)
selected_criteria_files = []

if accumulated_files:
    st.sidebar.markdown("**📌 반영할 채점 기준 선택**")
    for file_name in accumulated_files:
        if st.sidebar.checkbox(file_name, value=True, key=f"check_{file_name}"):
            selected_criteria_files.append(file_name)
    
    if st.sidebar.button("🗑️ 선택 파일 DB에서 삭제", type="secondary", key="delete_criteria_btn"):
        for file_name in accumulated_files:
            if st.session_state.get(f"check_{file_name}", False):
                os.remove(os.path.join(CRITERIA_DB_DIR, file_name))
        st.rerun()

# --- 5. 메인 화면 헤더 및 실시간 채점 기준표 노출 ---
st.title("🏫 브니엘고등학교 AI 생기부 정밀 평가 시스템")

is_unselected = ("선택" in selected_feedback_type) or (selected_feedback_type == "미선택")
display_mode_str = selected_feedback_type if not is_unselected else "영역 미선택 (좌측 사이드바에서 선택)"

st.markdown(f"**현재 관점:** `{evaluator_mode}` | **선택된 피드백 모드:** `<font color='#1E3A8A'><b>{display_mode_str}</b></font>` | **적용 기준 파일:** `{len(selected_criteria_files)}개`", unsafe_allow_html=True)

st.markdown("### 📋 AI 실시간 통합 채점 기준표 (메인 상시 노출)")

# 📌 [경로 A] 피드백 영역 미선택 시
if is_unselected:
    st.warning("👈 **왼쪽 사이드바의 [2. 평가 및 피드백 버전 선택]에서 피드백 대분류와 세부 평가 영역을 먼저 선택해 주세요.**")

# 📌 [경로 B-1] 과세특 7대 점검 항목 표 노출
elif selected_feedback_type == "과목세부능력 특기사항 전용 피드백":
    st.info("💡 **과목 세부능력 특기사항 교사 자가점검 7대 핵심 채점기준표 (100점 만점)**")
    st.markdown("""
    <div style="background-color: #F8FAFC; border: 1.5px solid #CBD5E1; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
        <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14.5px;">
            <thead>
                <tr style="background-color: #1E3A8A; color: white;">
                    <th style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; width: 60px;">번호</th>
                    <th style="padding: 10px; border: 1px solid #CBD5E1; width: 340px;">과세특 교사 7대 점검 항목</th>
                    <th style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; width: 80px;">배점</th>
                    <th style="padding: 10px; border: 1px solid #CBD5E1;">핵심 점검 내용 및 세부 가이드</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background-color: #EFF6FF;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">1</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">학생의 교과적 역량을 잘 보여주는 기록인가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">20점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">단순 수업 참여를 넘어 교과 개념의 깊이 있는 이해와 지적 도약이 드러나는가 (수학, 영어, 통합사회/과학 등 전 과목 포함)</td>
                </tr>
                <tr style="background-color: #EFF6FF;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">2</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">교사의 관찰이 들어간 기록인가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">20점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">학생 보고서 요약이 아닌 수업 중 교사가 직접 관찰한 행동과 질문이 기재되었는가</td>
                </tr>
                <tr style="background-color: #EFF6FF;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">3</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">교과의 역량이 들어갔는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">20점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">해당 교과목 고유의 핵심 성취기준 및 사고방식이 반영되었는가</td>
                </tr>
                <tr style="background-color: #FEF3C7;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">4</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">학생 간 복붙한 기록이 없는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">수강생 전체/일부 간 동일한 서술어나 표준화된 문장이 반복적으로 쓰이지 않았는가</td>
                </tr>
                <tr style="background-color: #FEF3C7;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">5</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">AI를 너무 돌려 맥락에 맞지 않는 단어나 문장이 들어가지 않았는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">구체적 사례 없이 거대 담론이나 어색한 AI 생성 표현만 나열되어 있지 않은가</td>
                </tr>
                <tr style="background-color: #F3F4F6;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">6</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">가독성이 높은가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">동기-과정-성장의 논리적 구조를 갖추고 문장의 호응과 전달력이 완벽한가</td>
                </tr>
                <tr style="background-color: #F3F4F6;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">7</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">생기부 기재 금지 사항이 잘 반영되었는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">대학명, 기관명, 상호명, 강사명 등 기재 불가능한 항목이 철저히 배제되었는가</td>
                </tr>
            </tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)

# 📌 [경로 B-2] 동아리 8대 점검 항목 표 노출
elif selected_feedback_type == "동아리 특기사항 전용 피드백":
    st.info("💡 **동아리 특기사항 교사 자가점검 8대 핵심 채점기준표 (100점 만점)**")
    st.markdown("""
    <div style="background-color: #F8FAFC; border: 1.5px solid #CBD5E1; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
        <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 14.5px;">
            <thead>
                <tr style="background-color: #1E3A8A; color: white;">
                    <th style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; width: 60px;">번호</th>
                    <th style="padding: 10px; border: 1px solid #CBD5E1; width: 340px;">동아리 교사 8대 점검 항목</th>
                    <th style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; width: 80px;">배점</th>
                    <th style="padding: 10px; border: 1px solid #CBD5E1;">핵심 점검 내용 및 세부 가이드</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background-color: #EFF6FF;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">1</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">학생의 학문적 탐구 역량을 잘 보여주는 기록인가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">15점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">동아리 활동 속에서 심화된 지적 호기심과 학문적 깊이가 드러나는가</td>
                </tr>
                <tr style="background-color: #EFF6FF;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">2</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">교사의 관찰이 들어간 기록인가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">15점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">단순 동아리 소개나 활동 나열이 아닌 지도교사의 구체적 관찰 사실이 기재되었는가</td>
                </tr>
                <tr style="background-color: #EFF6FF;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">3</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">학생이 이수한 교과목에서 심화 탐구한 내용이 들어갔는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">15점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">정규 교과 지식을 동아리 활동 속에서 어떻게 확장하고 심화했는지 연결고리가 있는가</td>
                </tr>
                <tr style="background-color: #FEF3C7;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">4</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">학생 간 복붙한 기록이 없는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">동아리 부원 전원에게 동일하게 적용된 복사-붙여넣기식 서술이 배제되었는가</td>
                </tr>
                <tr style="background-color: #FEF3C7;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">5</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">AI를 너무 돌려 맥락에 맞지 않는 단어나 문장이 들어가지 않았는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">개인별 구체적 역할 없이 거대 담론이나 어색한 AI 생성 표현만 가득하지 않은가</td>
                </tr>
                <tr style="background-color: #F3F4F6;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">6</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">가독성이 높은가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">15점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">주도적 동기, 협업 과정, 성장의 서사가 논리적으로 매끄럽게 연결되는가</td>
                </tr>
                <tr style="background-color: #F3F4F6;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">7</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">생기부 기재 금지 사항이 잘 반영되어 있는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">외부 기관명, 대회 명칭, 인증 시험명 등 기재 불가 항목이 철저히 배제되었는가</td>
                </tr>
                <tr style="background-color: #F3F4F6;">
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold; text-align: center;">8</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; font-weight: bold;">오탈자가 없는가</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1; text-align: center; font-weight: bold; color: #DC2626;">10점</td>
                    <td style="padding: 10px; border: 1px solid #CBD5E1;">맞춤법, 띄어쓰기, 문장 부호 등의 오탈자가 완벽하게 검수되었는가</td>
                </tr>
            </tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)

# 📌 [경로 C] 기타 생기부 영역 및 학생용 탭 선택 시 삼분 배점 기준표 표출
else:
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        st.info("📕 **1. 학업역량 (40점 만점)**")
        st.markdown("- **성취도 분포 및 이수환경의 상대적 우위성**: 공통과목(공통수학, 영어 등) 및 선택과목 종합 해석")
        st.markdown("- **행동 동기 및 어려움 극복 서사 기반 학업태도**: 교사 직접 관찰 기반 자발적 탐구 열의")
        st.markdown("- **디지털 리터러시 및 비판적 미디어 탐구 역량**: Bloom 5-6단계 사고 및 비판적 미디어 활용")
    with col_c2:
        st.success("📗 **2. 진로역량 (40점 만점)**")
        st.markdown("- **전공 연계 교과의 위계적 이수 노력**: 권장 이수과목, 과목 위계성 및 선택 동기")
        st.markdown("- **전공 관련 주요 교과 성취도 차별성**: 전공 관련 교과 성취도 차별성 및 전공적 사고")
        st.markdown("- **교과-창체 연계 진로 에피소드**: 문헌 비판적 독해 및 활동 간 수직/수평적 일관성")
    with col_c3:
        st.warning("📘 **3. 공동체역량 (20점 만점)**")
        st.markdown("- **다원적 환경에서의 협업 및 소통 역량**: 실질적 역할 기여 및 갈등/오해 조율")
        st.markdown("- **특정 대상을 도운 구체적 나눔과 배려**: 구체적 에피소드 중심의 사회적 가치 실천")
        st.markdown("- **성실성과 규칙 준수 및 자발적 리더십**: 무단 출결 배제, 규칙 준수 및 솔선수범")

st.divider()

# --- 6. PDF 및 DOCX 보고서 생성 함수 ---
def generate_pdf_report(eval_data, student_filename, mode, fb_type):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    
    font_path = get_korean_font_path()
    font_name = "Helvetica"
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", font_path))
            font_name = "KoreanFont"
        except Exception:
            pass

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontName=font_name, fontSize=15, leading=19, textColor=colors.HexColor('#1E3A8A'), alignment=1, spaceAfter=8)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName=font_name, fontSize=8.5, leading=11, textColor=colors.HexColor('#4B5563'), alignment=1, spaceAfter=12)
    h1_style = ParagraphStyle('H1', parent=styles['Heading2'], fontName=font_name, fontSize=11, leading=14, textColor=colors.HexColor('#1E3A8A'), spaceBefore=8, spaceAfter=4, keepWithNext=True)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName=font_name, fontSize=8, leading=11, textColor=colors.HexColor('#1F2937'), spaceAfter=3)
    
    def create_box(text, bg_hex, border_hex, text_hex):
        inner_style = ParagraphStyle('BoxInner', fontName=font_name, fontSize=7.5, leading=10, textColor=colors.HexColor(text_hex))
        p = Paragraph(text, inner_style)
        t = Table([[p]], colWidths=[520])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(bg_hex)),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor(border_hex)),
            ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))
        return t

    story = []
    story.append(Paragraph(f"🎓 브니엘고 AI 생기부 평가 리포트 ({mode})", title_style))
    story.append(Paragraph(f"대상 파일: {student_filename}  |  평가 모드: {fb_type}", subtitle_style))
    story.append(Spacer(1, 4))
    
    if fb_type == "과목세부능력 특기사항 전용 피드백" and "setuk_eval" in eval_data:
        st_data = eval_data["setuk_eval"]
        t_scores = st_data.get("scores", {})
        table_data = [
            [Paragraph("<b>과세특 교사 7대 점검 항목</b>", body_style), Paragraph("<b>배점</b>", body_style), Paragraph("<b>획득 점수</b>", body_style)],
            [Paragraph("1. 학생의 교과적 역량 서술", body_style), Paragraph("20점", body_style), Paragraph(f"{t_scores.get('academic_competence', 0)}점", body_style)],
            [Paragraph("2. 교사의 직접 관찰 반영", body_style), Paragraph("20점", body_style), Paragraph(f"{t_scores.get('teacher_observation', 0)}점", body_style)],
            [Paragraph("3. 교과의 핵심 역량 기재", body_style), Paragraph("20점", body_style), Paragraph(f"{t_scores.get('subject_competence', 0)}점", body_style)],
            [Paragraph("4. 학생 간 복붙 기재 여부", body_style), Paragraph("10점", body_style), Paragraph(f"{t_scores.get('duplication', 0)}점", body_style)],
            [Paragraph("5. AI 대필 / 문맥 어색함 검증", body_style), Paragraph("10점", body_style), Paragraph(f"{t_scores.get('ai_overuse', 0)}점", body_style)],
            [Paragraph("6. 가독성 및 문장 구조", body_style), Paragraph("10점", body_style), Paragraph(f"{t_scores.get('readability', 0)}점", body_style)],
            [Paragraph("7. 생기부 기재 금지 사항 준수", body_style), Paragraph("10점", body_style), Paragraph(f"{t_scores.get('prohibited_items', 0)}점", body_style)],
            [Paragraph("<b>✨ 최종 과세특 작성 품질 총점</b>", body_style), Paragraph("<b>100점</b>", body_style), Paragraph(f"<b><font color='#EF4444'>{t_scores.get('total', 0)} / 100</font></b>", body_style)]
        ]
        t_score = Table(table_data, colWidths=[220, 100, 200])
        t_score.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')), ('BACKGROUND', (0,8), (-1,8), colors.HexColor('#FEF2F2'))]))
        story.append(t_score)
        story.append(Spacer(1, 10))
        story.append(Paragraph("👩‍🏫 [과세특 개선 피드백 리포트]", h1_style))
        story.append(Paragraph(f"• <b>종합 총평:</b> {st_data.get('overall_summary', '')}", body_style))
        story.append(Paragraph(f"• <b>기재 우수 사항:</b> {st_data.get('good_points', '')}", body_style))
        story.append(Paragraph(f"• <b>보완 및 수정 필요사항:</b> {st_data.get('improvements', '')}", body_style))
        story.append(Spacer(1, 4))
        story.append(create_box(f"<b>✏️ 수정·보완 추천 문장 가이드:</b><br/>{st_data.get('revision_examples', '')}", '#FEF2F2', '#EF4444', '#991B1B'))
    elif fb_type == "동아리 특기사항 전용 피드백" and "club_eval" in eval_data:
        c_data = eval_data["club_eval"]
        c_scores = c_data.get("scores", {})
        table_data = [
            [Paragraph("<b>동아리 교사 8대 점검 항목</b>", body_style), Paragraph("<b>배점</b>", body_style), Paragraph("<b>획득 점수</b>", body_style)],
            [Paragraph("1. 학생의 학문적 탐구 역량", body_style), Paragraph("15점", body_style), Paragraph(f"{c_scores.get('academic_inquiry', 0)}점", body_style)],
            [Paragraph("2. 교사의 직접 관찰 반영", body_style), Paragraph("15점", body_style), Paragraph(f"{c_scores.get('teacher_observation', 0)}점", body_style)],
            [Paragraph("3. 교과목 심화 탐구 연계", body_style), Paragraph("15점", body_style), Paragraph(f"{c_scores.get('subject_connection', 0)}점", body_style)],
            [Paragraph("4. 학생 간 복붙 기재 여부", body_style), Paragraph("10점", body_style), Paragraph(f"{c_scores.get('duplication', 0)}점", body_style)],
            [Paragraph("5. AI 대필 / 문맥 어색함 검증", body_style), Paragraph("10점", body_style), Paragraph(f"{c_scores.get('ai_overuse', 0)}점", body_style)],
            [Paragraph("6. 가독성 및 문장 구조", body_style), Paragraph("15점", body_style), Paragraph(f"{c_scores.get('readability', 0)}점", body_style)],
            [Paragraph("7. 생기부 기재 금지 사항 준수", body_style), Paragraph("10점", body_style), Paragraph(f"{c_scores.get('prohibited_items', 0)}점", body_style)],
            [Paragraph("8. 오탈자 검수", body_style), Paragraph("10점", body_style), Paragraph(f"{c_scores.get('typo_check', 0)}점", body_style)],
            [Paragraph("<b>✨ 최종 동아리 작성 품질 총점</b>", body_style), Paragraph("<b>100점</b>", body_style), Paragraph(f"<b><font color='#EF4444'>{c_scores.get('total', 0)} / 100</font></b>", body_style)]
        ]
        t_score = Table(table_data, colWidths=[220, 100, 200])
        t_score.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')), ('BACKGROUND', (0,9), (-1,9), colors.HexColor('#FEF2F2'))]))
        story.append(t_score)
        story.append(Spacer(1, 10))
        story.append(Paragraph("👩‍🏫 [동아리 특기사항 개선 피드백 리포트]", h1_style))
        story.append(Paragraph(f"• <b>종합 총평:</b> {c_data.get('overall_summary', '')}", body_style))
        story.append(Paragraph(f"• <b>기재 우수 사항:</b> {c_data.get('good_points', '')}", body_style))
        story.append(Paragraph(f"• <b>보완 및 수정 필요사항:</b> {c_data.get('improvements', '')}", body_style))
        story.append(Spacer(1, 4))
        story.append(create_box(f"<b>✏️ 수정·보완 추천 문장 가이드:</b><br/>{c_data.get('revision_examples', '')}", '#FEF2F2', '#EF4444', '#991B1B'))
    else:
        scores = eval_data.get("scores", {})
        table_data = [
            [Paragraph("<b>평가 영역</b>", body_style), Paragraph("<b>반영 요소</b>", body_style), Paragraph("<b>취득 점수</b>", body_style)],
            [Paragraph("I. 학업역량 (40점)", body_style), Paragraph("성취도 분포 / 학업태도 / 비판적 탐구", body_style), Paragraph(f"<b>{scores.get('academic', 0)} / 40</b>", body_style)],
            [Paragraph("II. 진로역량 (40점)", body_style), Paragraph("전공 이수 노력 / 전공 성취도 / 진로 탐색", body_style), Paragraph(f"<b>{scores.get('career', 0)} / 40</b>", body_style)],
            [Paragraph("III. 공동체역량 (20점)", body_style), Paragraph("협업·소통 / 나눔·배려 / 성실성 / 리더십", body_style), Paragraph(f"<b>{scores.get('community', 0)} / 20</b>", body_style)],
            [Paragraph("<b>✨ 최종 환산 총점</b>", body_style), Paragraph("<b>100점 만점 기준 종합 환산점수</b>", body_style), Paragraph(f"<b><font color='#EF4444'>{scores.get('total', 0)} / 100</font></b>", body_style)]
        ]
        t_score = Table(table_data, colWidths=[120, 280, 120])
        t_score.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')), ('BACKGROUND', (0,4), (-1,4), colors.HexColor('#FEF2F2'))]))
        story.append(t_score)
        story.append(Spacer(1, 10))
        if "teacher_feedback" in eval_data:
            story.append(Paragraph(f"👩‍🏫 [교사전용 정밀 피드백: {fb_type}]", h1_style))
            tf = eval_data["teacher_feedback"]
            story.append(Paragraph(f"• <b>👍 장점 분석:</b> {tf.get('strength', '')}", body_style))
            story.append(Paragraph(f"• <b>⚠️ 보완점 및 감점 원인:</b> {tf.get('weakness', '')}", body_style))
            if tf.get('quote'):
                story.append(create_box(f"<b>🎯 원문 인용 근거:</b> \"{tf['quote']}\"", '#FEF3C7', '#F59E0B', '#451A03'))
        if "student_feedback" in eval_data:
            story.append(Paragraph("🎓 [학생전용 현위치 진단 & 솔루션]", h1_style))
            sf = eval_data["student_feedback"]
            story.append(Paragraph("<b>1. 입학사정관 관점 냉정한 현위치 진단 (지원 가능 대학 라인)</b>", body_style))
            story.append(create_box(sf.get("current_position", ""), '#F3F4F6', '#9CA3AF', '#111827'))
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"• <b>강점:</b> {sf.get('strength_analysis', '')}", body_style))
            story.append(Paragraph(f"• <b>치명적 약점:</b> {sf.get('weakness_analysis', '')}", body_style))
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>2. 향후 보완 추천 활동 및 구체적 탐구 주제 솔루션</b>", body_style))
            story.append(create_box(sf.get("recommendation", ""), '#FEF2F2', '#EF4444', '#991B1B'))
        
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

def generate_docx_report(eval_data, student_filename, mode, fb_type):
    if not DOCX_AVAILABLE:
        return None
    doc = Document()
    doc.add_heading(f"브니엘고 AI 생기부 평가 리포트 ({mode})", 0)
    doc.add_paragraph(f"대상 파일: {student_filename} | 평가 모드: {fb_type}")
    
    if fb_type == "과목세부능력 특기사항 전용 피드백" and "setuk_eval" in eval_data:
        st_data = eval_data["setuk_eval"]
        doc.add_heading("과세특 교사 7대 점검 항목 평가", level=1)
        scores = st_data.get("scores", {})
        doc.add_paragraph(f"최종 과세특 작성 품질 총점: {scores.get('total', 0)} / 100")
        doc.add_heading("종합 평어", level=2)
        doc.add_paragraph(st_data.get("overall_summary", ""))
        doc.add_heading("우수 사항", level=2)
        doc.add_paragraph(st_data.get("good_points", ""))
        doc.add_heading("보완 및 수정 필요사항", level=2)
        doc.add_paragraph(st_data.get("improvements", ""))
        doc.add_heading("수정 추천 문장 예시", level=2)
        doc.add_paragraph(st_data.get("revision_examples", ""))
    elif fb_type == "동아리 특기사항 전용 피드백" and "club_eval" in eval_data:
        c_data = eval_data["club_eval"]
        doc.add_heading("동아리 교사 8대 점검 항목 평가", level=1)
        scores = c_data.get("scores", {})
        doc.add_paragraph(f"최종 동아리 작성 품질 총점: {scores.get('total', 0)} / 100")
        doc.add_heading("종합 평어", level=2)
        doc.add_paragraph(c_data.get("overall_summary", ""))
        doc.add_heading("우수 사항", level=2)
        doc.add_paragraph(c_data.get("good_points", ""))
        doc.add_heading("보완 및 수정 필요사항", level=2)
        doc.add_paragraph(c_data.get("improvements", ""))
        doc.add_heading("수정 추천 문장 예시", level=2)
        doc.add_paragraph(c_data.get("revision_examples", ""))
    else:
        scores = eval_data.get("scores", {})
        doc.add_heading("100점 만점 영역별 스코어 카드", level=1)
        doc.add_paragraph(f"학업역량: {scores.get('academic', 0)} / 40")
        doc.add_paragraph(f"진로역량: {scores.get('career', 0)} / 40")
        doc.add_paragraph(f"공동체역량: {scores.get('community', 0)} / 20")
        doc.add_paragraph(f"최종 환산 총점: {scores.get('total', 0)} / 100")
        
        if "teacher_feedback" in eval_data:
            doc.add_heading(f"교사전용 피드백 ({fb_type})", level=1)
            tf = eval_data["teacher_feedback"]
            doc.add_paragraph(f"장점 분석: {tf.get('strength', '')}")
            doc.add_paragraph(f"보완점 및 감점 원인: {tf.get('weakness', '')}")
            if tf.get('quote'):
                doc.add_paragraph(f"원문 인용 근거: \"{tf['quote']}\"")
                
        if "student_feedback" in eval_data:
            doc.add_heading("학생전용 현위치 진단 & 솔루션", level=1)
            sf = eval_data["student_feedback"]
            doc.add_paragraph(f"현재 위치 진단: {sf.get('current_position', '')}")
            doc.add_paragraph(f"활동 강점: {sf.get('strength_analysis', '')}")
            doc.add_paragraph(f"치명적 약점: {sf.get('weakness_analysis', '')}")
            doc.add_paragraph(f"추천 탐구 주제 솔루션: {sf.get('recommendation', '')}")
            
    doc_buffer = BytesIO()
    doc.save(doc_buffer)
    return doc_buffer.getvalue()

# --- 7. 학생부 PDF 제출 및 AI 평가 구역 ---
st.markdown("### 📂 학생부 PDF 제출 및 맞춤형 AI 채점")
st.caption("🔒 제출한 생기부 PDF는 디스크에 저장되지 않으며, RAM에서 읽어 평가 후 즉시 영구 휘발 삭제됩니다.")

student_file = st.file_uploader("학생부 PDF 업로드", type=["pdf"], key="student_pdf_uploader")

if student_file and api_key:
    st.success(f"📎 학생부 파일 로드 완료: {student_file.name}")
    
    if is_unselected:
        st.warning("⚠️ 왼쪽 사이드바에서 [피드백 대분류 및 세부 평가 영역]을 먼저 선택해야 AI 평가를 시작할 수 있습니다.")
    else:
        if st.button("🔥 선택한 버전으로 AI 정밀 평가 시작하기", type="primary", use_container_width=True, key="start_eval_btn"):
            with st.spinner(f"🧠 AI 사정관이 [{evaluator_mode}] 관점에서 [{selected_feedback_type}] 맞춤 정밀 검증을 진행 중입니다..."):
                
                # RAM 상에서 읽기 (팩트 기반 텍스트 추출)
                student_text = extract_text_from_pdf_stream(student_file)
                
                if not student_text.strip():
                    st.error("❌ PDF에서 텍스트를 추출하지 못했습니다. 빈 문서이거나 이미지 스캔본인지 확인하세요.")
                    st.stop()
                    
                criteria_full_text = ""
                for fname in selected_criteria_files:
                    criteria_full_text += f"\n--- [{fname}] ---\n" + load_local_file_text(fname)[:1500]
                
                if not criteria_full_text:
                    criteria_full_text = "2028학년도 대입 표준 학종 평가 지표 적용"

                # [분기 1] 과목 세부능력 특기사항 전용 피드백
                if selected_feedback_type == "과목세부능력 특기사항 전용 피드백":
                    prompt = f"""
                    당신은 대학 입학사정관이자 교과세특 작성 컨설팅 전문가입니다.
                    제공된 [과목세특 텍스트]에는 수학(공통수학 등), 영어(공통영어 등), 통합사회, 통합과학 등 다양한 교과목의 세특 기재 내용이 포함되어 있습니다.
                    
                    [절대 준수 원칙 - 환각 방지]:
                    - 반드시 업로드된 [과목세특 텍스트]에 실제 기재된 사실과 문구만을 근거로 삼아 평가해야 합니다.
                    - 학생이 하지 않은 활동이나 생기부에 없는 내용을 AI가 스스로 지어내어 평가하거나 없는 사실을 가공해서는 절대 안 됩니다.
                    - 문서 내 특정 과목이나 내용이 다소 간결하거나 일부 누락되어 있더라도 에러를 내지 말고, 존재하는 텍스트의 맥락을 최대한 기반으로 하여 아래 7가지 채점기준(100점 만점)에 맞춰 정밀하게 평가하세요.

                    [생기부 문체 규정 - 절대 준수]:
                    - 학교생활기록부(세특)는 반드시 명사형 종결(예: ~함, ~음, ~보임, ~수행함, ~드러냄, ~탐구함)로 마무리되어야 하는 공식 문서입니다.
                    - 절대로 "-습니다", "-합니다", "-했습니다"와 같은 평서문 종결형으로 고치라는 피드백이나 수정 예시를 제시하지 마세요. 이는 생기부 작성 규정 위반이므로 명백한 오류입니다.
                    - 문장을 수정 제안할 때도 반드시 명사형 종결 어미를 유지한 채로 수정하세요.

                    [1~3번 항목: 근거 기반 촘촘한 피드백 원칙]:
                    - 1번(교과적 역량), 2번(교사 관찰), 3번(교과 역량) 항목은 두루뭉술한 총평이 아니라, 반드시 학생부 원문에서 실제 문장(또는 핵심 구절)을 최소 1개 이상 직접 인용하여 "왜 이 문장이 해당 항목을 충족/미충족하는지"를 구체적으로 짚어내세요.
                    - 단순히 "잘 드러남" 수준이 아니라, 어떤 개념적 깊이, 어떤 관찰 행동, 어떤 교과 고유의 사고방식이 어느 문장에서 드러나는지 문장 단위로 근거를 제시하세요.
                    - 부족한 경우, 어떤 요소(예: 교사의 1인칭 관찰 시점 부재, 개념어와 활동의 연결 고리 부족 등)가 빠졌는지 구체적으로 지적하세요.

                    [4~6번 항목: 냉정하고 철저한 정밀 검증 원칙 - 매우 중요]:
                    - 4번(복붙 여부): 세특 전체 텍스트 내에서 여러 과목 또는 여러 문단에 걸쳐 동일하거나 거의 동일한 서술어, 문장 구조, 상투적 표현(예: "~을 통해 ~을 함양함", "~에 대한 이해를 높임" 등 정형화된 틀)이 반복되는지 문장 대 문장으로 비교하여 철저히 검증하세요. 발견 시 어느 문장과 어느 문장이 유사한지 구체적으로 지적하세요.
                    - 5번(AI 어색함): 구체적 활동/사례 없이 추상적이고 거대한 담론(예: "미래 사회에 기여하는 인재", "4차 산업혁명 시대") 위주로 서술되었는지, 그리고 문맥상 부자연스럽거나 과장된 수식어, 사람이 실제로 쓰지 않을 법한 어색한 한자어·기계적 번역투 표현이 있는지 문장 단위로 짚어내세요.
                    - 6번(가독성)은 아래 세부 기준으로 매우 엄격하게 검증하세요:
                      (a) 수식어구 중첩: 한 문장 안에 관형절이나 수식어가 2개 이상 중첩되어 핵심 내용이 바로 읽히지 않는 문장이 있는지 확인
                      (b) 주술 호응: 주어와 서술어(명사형 종결)가 문법적으로 자연스럽게 호응하는지, 주어가 바뀌었는데 서술어가 맞지 않는 경우는 없는지 확인
                      (c) 목적어 누락: 서술어가 요구하는 목적어나 대상이 생략되어 의미가 불완전한 문장이 있는지 확인
                      (d) 문장이 지나치게 길어 한 번에 읽고 이해하기 어려운 경우, 어느 지점에서 끊어야 하는지까지 구체적으로 제시
                      각 항목에서 발견된 문제는 반드시 원문 문장을 그대로 인용하고, 어느 부분이 왜 문제인지 정확히 짚은 뒤, 명사형 종결을 유지한 개선 예시 문장을 함께 제시하세요.

                    [과세특 교사 점검 채점기준 (100점 만점)]:
                    1. 학생의 교과적 역량을 잘 보여주는 기록인가 (20점 만점)
                    2. 교사의 관찰이 들어간 기록인가 (20점 만점)
                    3. 교과의 역량이 들어갔는가 (20점 만점)
                    4. 학생 간 복붙한 기록이 없는가 (10점 만점)
                    5. AI를 너무 돌려 맥락에 맞지 않는 단어나 문장이 들어가지 않았는가 (10점 만점)
                    6. 가독성이 높은가 (10점 만점)
                    7. 생기부 기재 금지 사항(대학명, 기관명, 상호명, 강사명 등)이 잘 반영되었는가 (10점 만점)

                    [업로드된 과목세특 모음 텍스트]:
                    {student_text[:8000]}

                    반드시 아래 지정된 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 절대 금지):
                    {{
                        "setuk_eval": {{
                            "scores": {{
                                "academic_competence": 17,
                                "teacher_observation": 16,
                                "subject_competence": 18,
                                "duplication": 9,
                                "ai_overuse": 8,
                                "readability": 8,
                                "prohibited_items": 10,
                                "total": 86
                            }},
                            "overall_summary": "수학, 영어, 통합사/과 등 과세특 기재 내용에 대한 입학사정관 관점의 팩트 기반 종합 평어",
                            "good_points": "1~3번 항목 기준, 원문 문장을 직접 인용하며 어떤 지점에서 교과 역량·교사 관찰·교과 사고방식이 잘 드러났는지 촘촘하게 짚은 분석",
                            "improvements": "4~6번 항목 기준, 복붙 의심 문장 대조, AI스러운 거대 담론·어색한 표현, 수식어 중첩·주술 불일치·목적어 누락 등 가독성 문제를 원문 인용과 함께 매우 구체적이고 냉정하게 지적한 내용 (단, '-습니다'체로 고치라는 피드백은 절대 포함하지 말 것)",
                            "revision_examples": "improvements에서 지적한 문제 문장들을 실제로 인용하고, 명사형 종결을 유지한 채 '수정 전 ➔ 수정 후' 형태로 구체적으로 다듬은 예시문 작성"
                        }}
                    }}
                    """

                # [분기 1-2] 동아리 특기사항 전용 피드백
                elif selected_feedback_type == "동아리 특기사항 전용 피드백":
                    prompt = f"""
                    당신은 대학 입학사정관이자 동아리활동 작성 컨설팅 전문가입니다.
                    제공된 [동아리 특기사항 텍스트]는 학생들의 동아리 활동 기재 모음입니다.
                    
                    [절대 준수 원칙 - 환각 방지]:
                    - 반드시 제공된 텍스트에 있는 사실만을 근거로 평가하세요. 없는 내용을 지어내지 마세요.

                    [동아리 교사 점검 채점기준 (100점 만점)]:
                    1. 학생의 학문적 탐구 역량을 잘 보여주는 기록인가 (15점 만점)
                    2. 교사의 관찰이 들어간 기록인가 (15점 만점)
                    3. 학생이 이수한 교과목에서 심화 탐구한 내용이 들어갔는가 (15점 만점)
                    4. 학생 간 복붙한 기록이 없는가 (10점 만점)
                    5. AI를 너무 돌려 맥락에 맞지 않는 단어나 문장이 들어가지 않았는가 (10점 만점)
                    6. 가독성이 높은가 (15점 만점)
                    7. 생기부 기재 금지 사항이 잘 반영되어 있는가 (10점 만점)
                    8. 오탈자가 없는가 (10점 만점)

                    [업로드된 동아리 텍스트]:
                    {student_text[:8000]}

                    반드시 아래 지정된 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 절대 금지):
                    {{
                        "club_eval": {{
                            "scores": {{
                                "academic_inquiry": 13,
                                "teacher_observation": 13,
                                "subject_connection": 13,
                                "duplication": 9,
                                "ai_overuse": 9,
                                "readability": 13,
                                "prohibited_items": 10,
                                "typo_check": 10,
                                "total": 90
                            }},
                            "overall_summary": "동아리 특기사항에 대한 입학사정관 관점의 팩트 기반 종합 평어",
                            "good_points": "학문적 탐구 역량 및 교과 연계 심화 탐구가 돋보이는 우수 사례 분석",
                            "improvements": "구체적 관찰 사실 부족, 복붙 표현, 금지사항 등 구체적 감점 및 보완점 사유",
                            "revision_examples": "진부하거나 미흡한 문장을 꼽고 교사 관찰 및 교과 연계 중심으로 어떻게 수정할지 '수정 전 ➔ 수정 후' 예시 작성"
                        }}
                    }}
                    """

                # [분기 2] 교사 전용 (생기부 종합) 피드백 (교사 기록 적절성, 가독성, 성적 수준 적절성, AI 남용 여부 및 향후 지도 방향 포함)
                elif feedback_category == "교사전용 피드백 버전":
                    prompt = f"""
                    당신은 전국 대학부종합전형 서류를 평가하는 [{evaluator_mode}]입니다.
                    제공된 [학생 생기부 텍스트]에는 수학, 영어, 통합사회, 통합과학 등 다양한 교과 기록이 포함되어 있습니다.
                    
                    [절대 준수 원칙 - 환각 방지]:
                    - 반드시 생기부 PDF에 실제로 적힌 텍스트 내용만을 근거로 평가하세요. 없는 내용을 만들어내지 마세요.

                    [핵심 평가 지침 (생기부 종합 전용 피드백)]:
                    1. 평가자 관점: '{evaluator_mode}' 특성 반영.
                    2. 학업(40점)/진로(40점)/공동체(20점) 총 100점 만점으로 점수를 매기세요.
                    3. 학생 성적과 활동에 대한 교사의 기록이 적절했는지 상세히 진단하세요:
                       - 교사의 관찰(구체적 행동이나 수업 태도 등)이 잘 드러났는지
                       - 기록의 가독성과 문장 구조가 매끄러운지
                       - 학생의 성적 수준(원점수, 과목 평균, 등급 등)에 어울리는 기록인지
                       - AI를 남용한 티(거대 담론 나열, 구체적 사례 부재 등)가 나는지 여부
                    4. 학생에게 앞으로 어떤 방향으로 활동을 보완하고 확장해야 할지 구체적인 지도 방향과 피드백을 제시하세요.

                    [학생 제출 텍스트]:
                    {student_text[:8000]}

                    반드시 아래 지정된 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 절대 금지):
                    {{
                        "scores": {{
                            "academic": 33.0,
                            "career": 32.5,
                            "community": 16.5,
                            "total": 82.0
                        }},
                        "teacher_feedback": {{
                            "category": "{selected_feedback_type}",
                            "strength": "교사 기록의 적절성(관찰, 가독성, 성적 수준 부합도 등) 측면에서의 우수한 장점 서술",
                            "weakness": "교사 기록의 보완점(AI 남용 흔적, 구체적 관찰 부족 등) 및 감점 사유 지적, 그리고 앞으로 학생을 어떤 방향으로 지도해야 할지에 대한 구체적 제언",
                            "quote": "텍스트에서 실제 인용한 핵심 문장"
                        }}
                    }}
                    """

                # [분기 3] 학생 전용 피드백
                else:
                    prompt = f"""
                    당신은 전국 대학부종합전형 서류를 평가하는 [{evaluator_mode}]입니다.
                    제공된 [학생 생기부 텍스트]에는 공통수학, 공통영어, 통합사회, 통합과학 등 다양한 과목 기록이 포함되어 있습니다.
                    
                    [절대 준수 원칙 - 환각 방지]:
                    - 반드시 실제 기재된 생기부 텍스트 내용만을 근거로 진단하세요. 지어낸 활동으로 평가하지 마세요.

                    [핵심 평가 지침]:
                    1. 평가자 관점: '{evaluator_mode}' 특성 반영.
                    2. 학업(40점)/진로(40점)/공동체(20점) 총 100점 만점으로 점수를 산출하세요.
                    3. 학생용 피드백: 헛된 희망을 주지 않는 입학사정관 관점의 냉정한 현재 위치 진단(지원 가능 대학 라인), 활동 강점과 치명적 약점, 앞으로 실행해야 할 구체적인 탐구 주제 및 활동 솔루션을 제시하세요.

                    [학생 제출 텍스트]:
                    {student_text[:8000]}

                    반드시 아래 지정된 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 절대 금지):
                    {{
                        "scores": {{
                            "academic": 33.0,
                            "career": 32.5,
                            "community": 16.5,
                            "total": 82.0
                        }},
                        "student_feedback": {{
                            "current_position": "입학사정관 관점 냉정한 현위치 진단 및 지원 가능 대학 라인",
                            "strength_analysis": "여태까지 한 활동의 핵심 강점 분석",
                            "weakness_analysis": "치명적인 약점 및 감점 요소 분석",
                            "recommendation": "앞으로 실행해야 할 구체적인 탐구 주제 및 과목 선택/활동 솔루션"
                        }}
                    }}
                    """

                try:
                    model = genai.GenerativeModel(model_option)
                    response = model.generate_content(prompt)
                    cleaned = response.text.strip().replace("```json", "").replace("```", "").strip()
                    result_json = json.loads(cleaned)
                    
                    st.session_state["eval_result"] = result_json
                    st.session_state["evaluated_filename"] = student_file.name
                    st.session_state["eval_mode_title"] = selected_feedback_type
                    st.success("🎉 분석 완료! 제출된 학생부 데이터는 메모리(RAM)에서 즉시 영구 파기되었습니다.")
                except json.JSONDecodeError:
                    st.error("⚠️ AI 응답 형식을 해석하는 데 실패했습니다. 한 번 더 실행하시거나 모델을 변경해 보세요.")
                    st.code(response.text)
                except Exception as e:
                    st.error(f"평가 중 오류가 발생했습니다: {e}")

# --- 8. 채점 결과 및 맞춤형 피드백 출력 구역 ---
if "eval_result" in st.session_state:
    res = st.session_state["eval_result"]
    fb_title = st.session_state.get("eval_mode_title", "")
    
    st.divider()
    
    # 📌 과목 세특 교사 점검 모드 결과 출력
    if fb_title == "과목세부능력 특기사항 전용 피드백" and "setuk_eval" in res:
        st_eval = res["setuk_eval"]
        scores = st_eval.get("scores", {})
        
        st.markdown(f"### 📊 과목세부능력 특기사항 교사 기재 점검 표 (`{evaluator_mode}` 기준)")
        st.metric("✨ 과세특 기재 품질 총점", f"{scores.get('total', 0)} / 100 점")
        
        st.divider()
        st.markdown("#### 📋 7대 세부 점검 항목별 점수")
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("1. 학생 교과역량", f"{scores.get('academic_competence', 0)} / 20점")
        sc2.metric("2. 교사 직접 관찰", f"{scores.get('teacher_observation', 0)} / 20점")
        sc3.metric("3. 교과 핵심 역량", f"{scores.get('subject_competence', 0)} / 20점")
        sc4.metric("4. 학생간 복붙 방지", f"{scores.get('duplication', 0)} / 10점")
        
        sc5, sc6, sc7, _ = st.columns(4)
        sc5.metric("5. AI 대필 오염 방지", f"{scores.get('ai_overuse', 0)} / 10점")
        sc6.metric("6. 가독성 및 문장", f"{scores.get('readability', 0)} / 10점")
        sc7.metric("7. 기재금지 사항 준수", f"{scores.get('prohibited_items', 0)} / 10점")
        
        st.divider()
        st.subheader("👩‍🏫 과세특 교사 자가점검 및 개선 피드백")
        st.info(f"**📝 종합 총평:** {st_eval.get('overall_summary', '')}")
        st.success(f"**👍 기재 우수 사항:** {st_eval.get('good_points', '')}")
        st.warning(f"**⚠️ 보완 및 수정 필요사항:** {st_eval.get('improvements', '')}")
        st.error(f"**✏️ 수정·보완 추천 문장 예시:**\n\n{st_eval.get('revision_examples', '')}")

    # 📌 동아리 교사 점검 모드 결과 출력
    elif fb_title == "동아리 특기사항 전용 피드백" and "club_eval" in res:
        c_eval = res["club_eval"]
        c_scores = c_eval.get("scores", {})
        
        st.markdown(f"### 📊 동아리 특기사항 교사 기재 점검 표 (`{evaluator_mode}` 기준)")
        st.metric("✨ 동아리 기재 품질 총점", f"{c_scores.get('total', 0)} / 100 점")
        
        st.divider()
        st.markdown("#### 📋 8대 세부 점검 항목별 점수")
        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("1. 학문적 탐구 역량", f"{c_scores.get('academic_inquiry', 0)} / 15점")
        cc2.metric("2. 교사 직접 관찰", f"{c_scores.get('teacher_observation', 0)} / 15점")
        cc3.metric("3. 교과 심화 연계", f"{c_scores.get('subject_connection', 0)} / 15점")
        cc4.metric("4. 복붙 방지", f"{c_scores.get('duplication', 0)} / 10점")
        
        cc5, cc6, cc7, cc8 = st.columns(4)
        cc5.metric("5. AI 오염 방지", f"{c_scores.get('ai_overuse', 0)} / 10점")
        cc6.metric("6. 가독성", f"{c_scores.get('readability', 0)} / 15점")
        cc7.metric("7. 기재금지 준수", f"{c_scores.get('prohibited_items', 0)} / 10점")
        cc8.metric("8. 오탈자 검수", f"{c_scores.get('typo_check', 0)} / 10점")
        
        st.divider()
        st.subheader("👩‍🏫 동아리 교사 자가점검 및 개선 피드백")
        st.info(f"**📝 종합 총평:** {c_eval.get('overall_summary', '')}")
        st.success(f"**👍 기재 우수 사항:** {c_eval.get('good_points', '')}")
        st.warning(f"**⚠️ 보완 및 수정 필요사항:** {c_eval.get('improvements', '')}")
        st.error(f"**✏️ 수정·보완 추천 문장 예시:**\n\n{c_eval.get('revision_examples', '')}")

    # 📌 표준 생기부 / 기타 교사 / 학생 피드백 출력
    else:
        scores = res.get("scores", {})
        st.markdown(f"### 📊 평가 스코어 카드 (`{evaluator_mode}` 관점 / `{fb_title}`)")
        
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        col_s1.metric("📕 학업역량", f"{scores.get('academic', 0)} / 40 점")
        col_s2.metric("📗 진로역량", f"{scores.get('career', 0)} / 40 점")
        col_s3.metric("📘 공동체역량", f"{scores.get('community', 0)} / 20 점")
        col_s4.metric("✨ 최종 종합 점수", f"{scores.get('total', 0)} / 100 점")
        
        st.divider()
        
        if "teacher_feedback" in res:
            st.subheader(f"👩‍🏫 NEIS 및 진학 지도용 교사전용 피드백 (`{fb_title}`)")
            tf = res["teacher_feedback"]
            st.success(f"**👍 핵심 장점:** {tf.get('strength', '')}")
            st.warning(f"**⚠️ 보완점 및 감점 사유:** {tf.get('weakness', '')}")
            if tf.get('quote'):
                st.info(f"**🎯 원문 인용 근거:** \"{tf.get('quote')}\"")

        if "student_feedback" in res:
            st.subheader("🎓 학생 전용 쓴소리 진단 및 탐구 솔루션 리포트")
            sf = res["student_feedback"]
            
            st.markdown("#### 🔍 1. 입학사정관 관점 냉정한 현재 위치 (지원 가능 대학 라인)")
            st.error(sf.get("current_position", ""))
            
            col_st1, col_st2 = st.columns(2)
            with col_st1:
                st.markdown("#### 👍 2. 기존 활동의 주요 강점")
                st.success(sf.get("strength_analysis", ""))
            with col_st2:
                st.markdown("#### 🚨 3. 치명적인 약점 및 감점 요소")
                st.warning(sf.get("weakness_analysis", ""))
                
            st.markdown("#### 🚀 4. 앞으로의 구체적 추천 활동 및 탐구 주제 솔루션")
            st.info(sf.get("recommendation", ""))

    st.divider()
    
    # --- 9. PDF / DOCX 다운로드 기능 (요구사항 5) ---
    st.markdown("### 📥 3단계: 정밀 진단 보고서 다운로드")
    d1, d2 = st.columns(2)
    
    with d1:
        if REPORTLAB_AVAILABLE:
            pdf_bytes = generate_pdf_report(
                res, 
                st.session_state.get("evaluated_filename", "student.pdf"), 
                evaluator_mode, 
                fb_title
            )
            st.download_button(
                label="📄 정밀 진단 보고서 PDF 다운로드",
                data=pdf_bytes,
                file_name=f"브니엘고_AI_생기부평가_{evaluator_mode}_{st.session_state.get('evaluated_filename', 'student').replace('.pdf','')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="download_pdf_btn"
            )
        else:
            st.warning("ReportLab 모듈이 누락되었습니다. (`pip install reportlab` 필요)")
            
    with d2:
        if DOCX_AVAILABLE:
            docx_bytes = generate_docx_report(
                res, 
                st.session_state.get("evaluated_filename", "student.pdf"), 
                evaluator_mode, 
                fb_title
            )
            st.download_button(
                label="📝 정밀 진단 보고서 WORD(DOCX) 다운로드",
                data=docx_bytes,
                file_name=f"브니엘고_AI_생기부평가_{evaluator_mode}_{st.session_state.get('evaluated_filename', 'student').replace('.pdf','')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                key="download_docx_btn"
            )
        else:
            st.warning("python-docx 모듈이 누락되었습니다. (`pip install python-docx` 필요)")
