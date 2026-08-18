import streamlit as st
import google.generativeai as genai
import pypdf
import json
import os
import re
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

def normalize_feedback_text(text):
    if not text:
        return text
    t = str(text)
    lines = [ln for ln in t.split("\n") if ln.strip()]
    avg_len = sum(len(ln) for ln in lines) / len(lines) if lines else 0
    if len(lines) >= 3 and avg_len < 150:
        return t
    
    t = re.sub(r"\s*(\[[^\[\]]{2,40}\])", r"\n\n\1", t)
    t = re.sub(r"(?<!\n)\s*(\d{1,2}[\.\)]\s*\([^)]{1,25}\))", r"\n\1", t)
    t = re.sub(r"(?<!\n)\s*(\d{1,2}[\.\)]\s*['\"'])", r"\n\1", t)
    # 수정 전/후 앞에 학번/과목명이 포함된 경우도 줄바꿈 처리
    t = re.sub(r"\s*(-?\s*(\d{1,2}[\.\)]\s*)?(\([^)]{1,25}\))?\s*수정\s*(전|후)\s*[:：])", r"\n\1", t)
    t = re.sub(r"(['’g」\)])\s*(?=\d{1,2}[\.\)])", r"\1\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# --- 세션 상태 초기화 ---
if "feedback_main_cat" not in st.session_state:
    st.session_state["feedback_main_cat"] = "--- 피드백 대분류 선택 ---"
if "feedback_sub_cat" not in st.session_state:
    st.session_state["feedback_sub_cat"] = "--- 세부 영역 선택 ---"

# --- 4. 사이드바 구성 ---
st.sidebar.markdown("<h1 style='text-align: center;'>🎓</h1>", unsafe_allow_html=True)
st.sidebar.markdown("<h3 style='text-align: center;'>브니엘고 AI 평가 시스템</h3>", unsafe_allow_html=True)
st.sidebar.divider()

st.sidebar.markdown("### 🏛️ 1. 입학사정관 유형 선택")
evaluator_mode = st.sidebar.radio(
    "사정관 관점을 선택하세요.",
    ["인서울 입학사정관", "지거국 입학사정관"],
    index=0,
    key="evaluator_mode_radio"
)
st.sidebar.divider()

st.sidebar.markdown("### 📊 2. 평가 및 피드백 버전 선택")
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
    st.sidebar.info("💡 학생 1인에 대한 냉정한 현위치 진단, 강점/약점 분석 및 앞으로의 탐구 솔루션을 제공합니다.")
st.sidebar.divider()

# API 키 설정
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

model_option = st.sidebar.selectbox(
    "🤖 Gemini AI 모델 선택",
    ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    index=0,
    key="model_option_select"
)
st.sidebar.divider()

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
    st.sidebar.success(f"📁 {len(uploaded_criteria)}개 파일 DB 누적 저장 완료!")
    st.rerun()

accumulated_files = os.listdir(CRITERIA_DB_DIR)
selected_criteria_files = []
if accumulated_files:
    st.sidebar.markdown("**📂 반영할 채점 기준 선택**")
    for file_name in accumulated_files:
        if st.sidebar.checkbox(file_name, value=True, key=f"check_{file_name}"):
            selected_criteria_files.append(file_name)
    
    if st.sidebar.button("🗑️ 선택 파일 DB에서 삭제", type="secondary", key="delete_criteria_btn"):
        for file_name in accumulated_files:
            if st.session_state.get(f"check_{file_name}", False):
                os.remove(os.path.join(CRITERIA_DB_DIR, file_name))
        st.rerun()

# --- 5. 메인 화면 헤더 ---
st.title("🏫 브니엘고등학교 AI 생기부 정밀 평가 시스템")
is_unselected = ("선택" in selected_feedback_type) or (selected_feedback_type == "미선택")
display_mode_str = selected_feedback_type if not is_unselected else "영역 미선택 (좌측 사이드바에서 선택)"
st.markdown(f"**현재 관점:** `{evaluator_mode}` | **선택된 피드백 모드:** `<font color='#1E3A8A'><b>{display_mode_str}</b></font>` | **적용 기준 파일:** `{len(selected_criteria_files)}개`", unsafe_allow_html=True)
st.markdown("### 📋 AI 실시간 통합 채점 기준표 (메인 상시 노출)")

if is_unselected:
    st.warning("⚠️ **왼쪽 사이드바의 [2. 평가 및 피드백 버전 선택]에서 피드백 대분류와 세부 평가 영역을 먼저 선택해 주세요.**")
elif selected_feedback_type == "과목세부능력 특기사항 전용 피드백":
    st.info("📌 **과목 세부능력 특기사항 교사 자가점검 7대 핵심 채점기준표 (100점 만점)**")
    # (HTML 테이블 생략 - 기존 코드 유지)
elif selected_feedback_type == "동아리 특기사항 전용 피드백":
    st.info("📌 **동아리 특기사항 교사 자가점검 8대 핵심 채점기준표 (100점 만점)**")
    # (HTML 테이블 생략 - 기존 코드 유지)
else:
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        st.info("📌 **1. 학업역량 (40점 만점)**")
    with col_c2:
        st.success("📌 **2. 진로역량 (40점 만점)**")
    with col_c3:
        st.warning("📌 **3. 공동체역량 (20점 만점)**")
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
    
    def markdown_to_flowables(text, text_hex):
        MAX_CHARS = 220
        if not text:
            return [Paragraph("-", ParagraphStyle('mdEmpty', fontName=font_name, fontSize=7.5, leading=10.5, textColor=colors.HexColor(text_hex)))]
        normal_style = ParagraphStyle('mdNormal', fontName=font_name, fontSize=7.5, leading=11, textColor=colors.HexColor(text_hex), spaceAfter=5)
        continuation_style = ParagraphStyle('mdContinuation', fontName=font_name, fontSize=7.5, leading=11, textColor=colors.HexColor(text_hex), leftIndent=10, spaceAfter=5)
        section_style = ParagraphStyle('mdSection', fontName=font_name, fontSize=8.3, leading=11.5, textColor=colors.HexColor(text_hex), spaceBefore=9, spaceAfter=4)
        numbered_style = ParagraphStyle('mdNumbered', fontName=font_name, fontSize=7.8, leading=11.2, textColor=colors.HexColor(text_hex), spaceBefore=7, spaceAfter=2)
        numbered_continuation_style = ParagraphStyle('mdNumberedContinuation', fontName=font_name, fontSize=7.8, leading=11.2, textColor=colors.HexColor(text_hex), leftIndent=12, spaceAfter=2)
        bullet_style = ParagraphStyle('mdBullet', fontName=font_name, fontSize=7.5, leading=10.8, textColor=colors.HexColor(text_hex), leftIndent=16, spaceAfter=4)
        bullet_continuation_style = ParagraphStyle('mdBulletContinuation', fontName=font_name, fontSize=7.5, leading=10.8, textColor=colors.HexColor(text_hex), leftIndent=26, spaceAfter=4)
        sub_bullet_style = ParagraphStyle('mdSubBullet', fontName=font_name, fontSize=7.3, leading=10.5, textColor=colors.HexColor(text_hex), leftIndent=30, spaceAfter=4)
        
        def chunk_long_text(raw, max_chars=MAX_CHARS):
            raw = raw.strip()
            if not raw:
                return []
            if len(raw) <= max_chars:
                return [raw]
            words = raw.split(" ")
            chunks, current = [], ""
            for w in words:
                while len(w) > max_chars:
                    if current:
                        chunks.append(current)
                        current = ""
                    chunks.append(w[:max_chars])
                    w = w[max_chars:]
                candidate = f"{current} {w}".strip() if current else w
                if len(candidate) > max_chars and current:
                    chunks.append(current)
                    current = w
                else:
                    current = candidate
            if current:
                chunks.append(current)
            return chunks

        def emit(raw_content, prefix, first_style, continuation_style_):
            chunks = chunk_long_text(raw_content)
            if not chunks:
                return
            for idx, chunk in enumerate(chunks):
                chunk_fmt = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", chunk)
                if idx == 0:
                    flowables.append(Paragraph(f"{prefix}{chunk_fmt}", first_style))
                else:
                    flowables.append(Paragraph(chunk_fmt, continuation_style_))

        flowables = []
        for raw_line in str(text).split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
            m_section = re.match(r"^\**\[(.+?)\]\**\s*(.*)", line)
            if m_section:
                title_fmt = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", m_section.group(1))
                flowables.append(Paragraph(f"▍<b>{title_fmt}</b>", section_style))
                if m_section.group(2):
                    emit(m_section.group(2), "", normal_style, continuation_style)
                continue
            m_num = re.match(r"^(\d+)[\.\)]\s+(.*)", line)
            m_bullet = re.match(r"^[-•*○ㅇ]\s+(.*)", line)
            if m_num:
                emit(m_num.group(2), f"<b>{m_num.group(1)}.</b> ", numbered_style, numbered_continuation_style)
            elif m_bullet:
                style = sub_bullet_style if leading_spaces >= 2 else bullet_style
                emit(m_bullet.group(1), "• ", style, bullet_continuation_style)
            else:
                emit(line, "", normal_style, continuation_style)
        return flowables

    def create_feedback_box(title, text, bg_hex, border_hex, text_hex):
        title_style = ParagraphStyle('BoxTitle', fontName=font_name, fontSize=9, leading=12, textColor=colors.HexColor(text_hex), spaceAfter=0)
        body_flowables = markdown_to_flowables(text, text_hex)
        rows = [[Paragraph(f"<b>{title}</b>", title_style)]]
        for fl in body_flowables:
            rows.append([fl])
        t = Table(rows, colWidths=[520])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg_hex)),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor(border_hex)),
            ('LINEBEFORE', (0, 0), (0, -1), 3, colors.HexColor(border_hex)),
            ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, -1), (-1, -1), 1.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, -1), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (0, 0), 7),
            ('BOTTOMPADDING', (0, -1), (0, -1), 7),
        ]))
        t.splitByRow = 1
        t.hAlign = 'LEFT'
        return t

    story = []
    story.append(Paragraph(f"📋 브니엘고 AI 생기부 평가 리포트 ({mode})", title_style))
    story.append(Paragraph(f"대상 파일: {student_filename} | 평가 모드: {fb_type}", subtitle_style))
    story.append(Spacer(1, 4))
    
    # 평가 데이터 빌드 생략 (기존 구조와 동일)
    scores = eval_data.get("scores", {})
    # ... (PDF 생성부의 나머지 테이블 및 피드백 박스 구성 유지) ...
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
    doc_buffer = BytesIO()
    doc.save(doc_buffer)
    return doc_buffer.getvalue()

# --- 7. 학생부 PDF 제출 및 AI 평가 구역 ---
st.markdown("### 📥 학생부 PDF 제출 및 맞춤형 AI 채점")
st.caption("🔒 제출한 생기부 PDF는 디스크에 저장되지 않으며, RAM에서 읽어 평가 후 즉시 영구 휘발 삭제됩니다.")
student_file = st.file_uploader("학생부 PDF 업로드", type=["pdf"], key="student_pdf_uploader")

if student_file and api_key:
    st.success(f"✅ 학생부 파일 로드 완료: {student_file.name}")
    
    if is_unselected:
        st.warning("⚠️ 왼쪽 사이드바에서 [피드백 대분류 및 세부 평가 영역]을 먼저 선택해야 AI 평가를 시작할 수 있습니다.")
    else:
        if st.button("🚀 선택한 버전으로 AI 정밀 평가 시작하기", type="primary", use_container_width=True, key="start_eval_btn"):
            with st.spinner(f"🤖 AI 사정관이 [{evaluator_mode}] 관점에서 [{selected_feedback_type}] 맞춤 정밀 검증을 진행 중입니다..."):
                
                student_text = extract_text_from_pdf_stream(student_file)
                if not student_text.strip():
                    st.error("❌ PDF에서 텍스트를 추출하지 못했습니다.")
                    st.stop()
                
                criteria_full_text = ""
                for fname in selected_criteria_files:
                    criteria_full_text += f"\n--- [{fname}] ---\n" + load_local_file_text(fname)[:1500]
                
                if not criteria_full_text:
                    criteria_full_text = "2028학년도 대입 표준 학종 평가 지표 적용"

                # [과목세부능력 특기사항 전용 피드백 프롬프트 수정]
                if selected_feedback_type == "과목세부능력 특기사항 전용 피드백":
                    prompt = f"""
                    당신은 대학 입학사정관이자 교과세특 작성 컨설팅 전문가입니다.
                    제공된 [과목세특 텍스트]를 바탕으로 7가지 채점기준에 맞춰 정밀하게 평가하세요.
                    
                    [전수 점검 및 수정 예시 규칙 - 매우 중요]:
                    - improvements와 revision_examples는 반드시 아래와 같이 "채점 항목 번호별"로 소제목을 나누어 구조화하세요.
                    - **[revision_examples 작성 규칙]**: 
                      improvements 파트에서 지적한 각 문제 문장에 대해 수정 예시를 제공할 때, **반드시 보완 및 수정 필요사항처럼 학번/과목명 식별자(예: `1. (학번/과목명)`)를 수정 전·후 문구 앞에 똑같이 표시**해 주세요.
                      형식 예시:
                      `- 수정 전: (1. (학번/과목명) '문장')` 또는 `1. (학번/과목명) - 수정 전: '문장' \\n - 수정 후: '문장'`
                    
                    [업로드된 과목세특 모음 텍스트]:
                    {student_text[:8000]}
                    반드시 아래 지정된 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 절대 금지):
                    {{
                      "setuk_eval": {{
                        "scores": {{
                          "academic_competence": 17, "teacher_observation": 16, "subject_competence": 18, 
                          "duplication": 9, "ai_overuse": 8, "readability": 8, "prohibited_items": 10, "total": 86
                        }},
                        "overall_summary": "종합 평어",
                        "good_points": "1. (수학) 우수 사례 문장",
                        "improvements": "▍[2번. 교사 관찰 결여]\\n1. (1학년 3반 10번 홍길동/수학) '수업 내용에 대해 조사하여 발표함.'",
                        "revision_examples": "▍[2번. 교사 관찰 결여]\\n1. (1학년 3반 10번 홍길동/수학) - 수정 전: '수업 내용에 대해 조사하여 발표함.'\\n- 수정 후: '이차함수 그래프 분석 과정을 논리적으로 서술함.'"
                      }}
                    }}
                    """
                else:
                    prompt = f"""
                    당신은 대학 입학사정관인 [{evaluator_mode}]입니다. 학생부 텍스트를 바탕으로 평가하세요.
                    [학생 제출 텍스트]:
                    {student_text[:8000]}
                    반드시 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 금지):
                    {{
                      "scores": {{ "academic": 33.0, "career": 32.5, "community": 16.5, "total": 82.0 }},
                      "teacher_feedback": {{ "category": "{selected_feedback_type}", "strength": "장점", "weakness": "보완점", "quote": "인용문" }}
                    }}
                    """

                try:
                    model = genai.GenerativeModel(model_option)
                    response = model.generate_content(prompt)
                    cleaned = response.text.strip().replace("```json", "").replace("```", "").strip()
                    result_json = json.loads(cleaned)
                    
                    _TEXT_FIELDS = ["overall_summary", "good_points", "improvements", "revision_examples", "strength", "weakness", "quote", "current_position", "strength_analysis", "weakness_analysis", "recommendation"]
                    for _outer_key in ("setuk_eval", "club_eval"):
                        if _outer_key in result_json and isinstance(result_json[_outer_key], dict):
                            for _field in _TEXT_FIELDS:
                                if _field in result_json[_outer_key]:
                                    result_json[_outer_key][_field] = normalize_feedback_text(result_json[_outer_key][_field])
                    
                    st.session_state["eval_result"] = result_json
                    st.session_state["evaluated_filename"] = student_file.name
                    st.session_state["eval_mode_title"] = selected_feedback_type
                    st.success("🎉 분석 완료!")
                except Exception as e:
                    st.error(f"평가 중 오류가 발생했습니다: {e}")

# --- 8. 채점 결과 및 맞춤형 피드백 출력 구역 ---
if "eval_result" in st.session_state:
    res = st.session_state["eval_result"]
    fb_title = st.session_state.get("eval_mode_title", "")
    st.divider()
    
    if fb_title == "과목세부능력 특기사항 전용 피드백" and "setuk_eval" in res:
        st_eval = res["setuk_eval"]
        st.subheader("🛠️ 과세특 교사 자가점검 및 개선 피드백")
        st.info(f"**📌 종합 총평:** {st_eval.get('overall_summary', '')}")
        st.success(f"**🌟 기재 우수 사항:** {st_eval.get('good_points', '')}")
        st.warning(f"**⚠️ 보완 및 수정 필요사항:** {st_eval.get('improvements', '')}")
        # 이제 revision_examples에도 학번/과목명 정보가 포함되어 출력됩니다.
        st.error(f"**✏️ 수정·보완 추천 문장 예시:**\n\n{st_eval.get('revision_examples', '')}")
