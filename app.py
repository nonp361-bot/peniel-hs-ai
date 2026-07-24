import streamlit as st
import google.generativeai as genai
import pypdf
import json
import os
import urllib.request
from io import BytesIO

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

# --- 3. 헬퍼 함수 (PDF 읽기, 한글 폰트) ---
def extract_text_from_pdf_stream(pdf_file):
    """RAM(메모리) 상에서 직접 PDF 텍스트 추출 - 휘발성"""
    if pdf_file is None:
        return ""
    try:
        pdf_reader = pypdf.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
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

# --- 4. 사이드바 구성 ---
st.sidebar.markdown("<h1 style='text-align: center;'>🎓</h1>", unsafe_allow_html=True)
st.sidebar.markdown("<h3 style='text-align: center;'>브니엘고 AI 평가 시스템</h3>", unsafe_allow_html=True)
st.sidebar.divider()

# 4-1. 입학사정관 선택 (요구사항 1)
st.sidebar.markdown("### 🎯 1. 입학사정관 유형 선택")
evaluator_mode = st.sidebar.radio(
    "사정관 관점을 선택하세요.",
    ["인서울 입학사정관", "지거국 입학사정관"],
    index=0
)

st.sidebar.divider()

# 4-2. 피드백 버전 선택 (요구사항 9 보완)
st.sidebar.markdown("### 📝 2. 평가 및 피드백 버전 선택")
feedback_category = st.sidebar.selectbox(
    "피드백 대분류를 선택하세요.",
    ["교사전용 피드백 버전", "학생용 피드백 버전"]
)

if feedback_category == "교사전용 피드백 버전":
    selected_feedback_type = st.sidebar.radio(
        "세부 평가 영역 선택",
        [
            "과목세부능력 특기사항 전용 피드백",
            "동아리 특기사항 전용 피드백",
            "자율 특기사항 전용 피드백",
            "진로 특기사항 전용 피드백",
            "행동발달특기사항 전용 피드백",
            "생기부 종합 전용 피드백"
        ]
    )
else:
    selected_feedback_type = "학생전용 피드백"
    st.sidebar.info("🎓 학생의 현위치 진단, 활동 장단점 및 앞으로의 구체적 탐구 솔루션을 제공합니다.")

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
    api_key = st.sidebar.text_input("🔑 구글 Gemini API Key 입력", type="password")
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
    index=0
)

st.sidebar.divider()

# 4-5. 채점 기준 파일 관리 (무제한 업로드 & 영구 보관)
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
    
    if st.sidebar.button("🗑️ 선택 파일 DB에서 삭제", type="secondary"):
        for file_name in accumulated_files:
            if st.session_state.get(f"check_{file_name}", False):
                os.remove(os.path.join(CRITERIA_DB_DIR, file_name))
        st.rerun()

# --- 5. 실시간 채점 기준표 자동 생성 및 갱신 ---
def get_dynamic_criteria_summary(files, mode, model_name):
    if not api_key or not files:
        return None
    
    combined_text = ""
    for fname in files:
        combined_text += f"\n--- [{fname}] ---\n" + load_local_file_text(fname)[:3000]
    
    prompt = f"""
    당신은 대학 입학사정관입니다. 업로드된 채점 기준 파일들을 통합 분석하여, 메인 화면에 표시할 세부 채점 기준표를 작성하세요.
    
    [평가자 관점]: {mode}
    [기본 배점 구조 고정]:
    1. 학업역량 (40점 만점)
    2. 진로역량 (40점 만점)
    3. 공동체역량 (20점 만점)

    [참고 채점 기준 문서]:
    {combined_text}

    오직 아래 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 표기 절대 금지):
    {{
        "academic_criteria": ["학업역량 세부지표 1", "학업역량 세부지표 2", "학업역량 세부지표 3"],
        "career_criteria": ["진로역량 세부지표 1", "진로역량 세부지표 2", "진로역량 세부지표 3"],
        "community_criteria": ["공동체역량 세부지표 1", "공동체역량 세부지표 2", "공동체역량 세부지표 3"]
    }}
    """
    try:
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt)
        cleaned = res.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return None

# --- 6. 메인 화면 헤더 및 실시간 채점 기준표 노출 ---
st.title("🏫 브니엘고등학교 AI 생기부 정밀 평가 시스템")
st.markdown(f"**현재 관점:** `{evaluator_mode}` | **선택된 피드백 모드:** `{selected_feedback_type}` | **적용 기준 파일:** `{len(selected_criteria_files)}개`")

st.markdown("### 📋 AI 실시간 통합 채점 기준표 (메인 상시 노출)")

if selected_criteria_files and api_key:
    cache_key = f"{evaluator_mode}_{'_'.join(selected_criteria_files)}_{model_option}"
    if "criteria_cache_key" not in st.session_state or st.session_state["criteria_cache_key"] != cache_key:
        with st.spinner("🔄 업로드된 파일들을 AI가 종합 분석하여 실시간 채점기준표를 구성 중입니다..."):
            st.session_state["dynamic_criteria"] = get_dynamic_criteria_summary(selected_criteria_files, evaluator_mode, model_option)
            st.session_state["criteria_cache_key"] = cache_key
    
    dyn = st.session_state.get("dynamic_criteria")
    if dyn:
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            st.info("📕 **1. 학업역량 (40점 만점)**")
            for item in dyn.get("academic_criteria", []):
                st.markdown(f"- {item}")
        with col_c2:
            st.success("📗 **2. 진로역량 (40점 만점)**")
            for item in dyn.get("career_criteria", []):
                st.markdown(f"- {item}")
        with col_c3:
            st.warning("📘 **3. 공동체역량 (20점 만점)**")
            for item in dyn.get("community_criteria", []):
                st.markdown(f"- {item}")
    else:
        st.info("💡 기본 채점기준 [학업(40) / 진로(40) / 공동체(20)] 지표가 적용됩니다.")
else:
    st.info("💡 사이드바에서 대학별 채점 기준 파일(PDF/TXT)을 업로드하고 선택하면 메인 화면의 세부 채점표가 자동 변경됩니다.")

st.divider()

# --- 7. PDF 리포트 생성 함수 (ReportLab) ---
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
    
    scores = eval_data.get("scores", {})
    table_data = [
        [Paragraph("<b>평가 영역</b>", body_style), Paragraph("<b>반영 요소</b>", body_style), Paragraph("<b>취득 점수</b>", body_style)],
        [Paragraph("I. 학업역량 (40점)", body_style), Paragraph("성취도 분포 / 학업태도 / 비판적 탐구", body_style), Paragraph(f"<b>{scores.get('academic', 0)} / 40</b>", body_style)],
        [Paragraph("II. 진로역량 (40점)", body_style), Paragraph("전공 이수 노력 / 전공 성취도 / 진로 탐색", body_style), Paragraph(f"<b>{scores.get('career', 0)} / 40</b>", body_style)],
        [Paragraph("III. 공동체역량 (20점)", body_style), Paragraph("협업·소통 / 나눔·배려 / 성실성 / 리더십", body_style), Paragraph(f"<b>{scores.get('community', 0)} / 20</b>", body_style)],
        [Paragraph("<b>✨ 최종 환산 총점</b>", body_style), Paragraph("<b>100점 만점 기준 종합 환산점수</b>", body_style), Paragraph(f"<b><font color='#EF4444'>{scores.get('total', 0)} / 100</font></b>", body_style)]
    ]
    t_score = Table(table_data, colWidths=[120, 280, 120])
    t_score.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('BACKGROUND', (0,4), (-1,4), colors.HexColor('#FEF2F2')),
    ]))
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

# --- 8. 학생부 PDF 제출 및 AI 평가 구역 ---
st.markdown("### 📂 학생부 PDF 제출 및 맞춤형 AI 채점")
st.caption("🔒 제출한 생기부 PDF는 디스크에 저장되지 않으며, RAM에서 읽어 평가 후 즉시 영구 휘발 삭제됩니다.")

student_file = st.file_uploader(f"학생부 PDF 업로드 (현재 설정: `{selected_feedback_type}` 모드)", type=["pdf"], key="student_pdf_uploader")

if student_file and api_key:
    st.success(f"📎 학생부 파일 로드 완료: {student_file.name}")
    
    if st.button("🔥 선택한 버전으로 AI 정밀 평가 시작하기", type="primary", use_container_width=True):
        with st.spinner(f"🧠 AI 사정관이 [{evaluator_mode}] 관점에서 [{selected_feedback_type}] 맞춤 정밀 검증을 진행 중입니다..."):
            
            # RAM 상에서 읽기 (개인정보 휘발)
            student_text = extract_text_from_pdf_stream(student_file)
            
            if not student_text.strip():
                st.error("❌ PDF에서 텍스트를 추출하지 못했습니다. 빈 문서이거나 이미지 스캔본인지 확인하세요.")
                st.stop()
                
            criteria_full_text = ""
            for fname in selected_criteria_files:
                criteria_full_text += f"\n--- [{fname}] ---\n" + load_local_file_text(fname)
            
            if not criteria_full_text:
                criteria_full_text = "2028학년도 대입 표준 학종 평가 지표 적용"

            # 선택된 모드에 따라 프롬프트 최적화
            prompt = f"""
            당신은 전국 대학부종합전형 서류를 평가하는 [{evaluator_mode}]입니다.
            제공된 [학생 생기부 텍스트]를 독해하고, 선택된 피드백 버전인 [{selected_feedback_type}]에 집중하여 정밀 평가와 피드백을 작성하세요.

            [핵심 평가 지침]:
            1. 평가자 관점: '{evaluator_mode}' 특성 반영.
               - 인서울: 학업 심화성, Bloom 5-6단계, 전문교과 이수, 지적 호기심 확장 중점
               - 지거국: 교과 충실도, 기초 학업역량, 권장 과목 이수, 성실성 중점
            2. 파일에 일부 영역(예: 과목세특)만 있더라도 해당 영역에 집중하여 학업(40점)/진로(40점)/공동체(20점) 총 100점 만점으로 점수를 합리적으로 산출하세요. 절대 에러를 내지 마세요.
            3. 선택된 모드 '{selected_feedback_type}'에 맞게 피드백을 작성하세요.
               - 교사전용 모드일 경우: 해당 영역에 대한 구체적 장점, 보완점/감점 사유, 세특 원문 문장 인용을 적으세요.
               - 학생전용 모드일 경우: 입학사정관 관점의 냉정한 현재 위치(지원 가능 대학 라인), 활동 강점, 치명적 약점, 향후 구체적 추천 탐구 주제 및 활동 솔루션을 적으세요.

            [채점 기준 참고 자료]:
            {criteria_full_text[:12000]}

            [학생 제출 텍스트]:
            {student_text[:15000]}

            반드시 아래 지정된 순수 JSON 형식으로만 응답하세요 (마크다운 ```json 기호 절대 금지):
            """

            if feedback_category == "교사전용 피드백 버전":
                prompt += f"""
                {{
                    "scores": {{
                        "academic": 33.0,
                        "career": 32.5,
                        "community": 16.5,
                        "total": 82.0
                    }},
                    "teacher_feedback": {{
                        "category": "{selected_feedback_type}",
                        "strength": "{selected_feedback_type} 관점에서의 탁월한 장점 상세 서술",
                        "weakness": "{selected_feedback_type} 관점에서의 보완점, 감점 사유, Bloom 단계 한계 및 AI 의심문장 지적",
                        "quote": "텍스트에서 실제 인용한 핵심 문장"
                    }}
                }}
                """
            else:
                prompt += """
                {
                    "scores": {
                        "academic": 33.0,
                        "career": 32.5,
                        "community": 16.5,
                        "total": 82.0
                    },
                    "student_feedback": {
                        "current_position": "입학사정관 관점 냉정한 현위치 진단 및 지원 가능 대학 라인",
                        "strength_analysis": "여태까지 한 활동의 핵심 강점 분석",
                        "weakness_analysis": "치명적인 약점 및 감점 요소 분석",
                        "recommendation": "앞으로 3학년 및 다음 학기에 실행해야 할 구체적인 탐구 주제 및 과목 선택/활동 솔루션"
                    }
                }
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

# --- 9. 채점 결과 및 맞춤형 피드백 출력 구역 ---
if "eval_result" in st.session_state:
    res = st.session_state["eval_result"]
    scores = res.get("scores", {})
    fb_title = st.session_state.get("eval_mode_title", "")
    
    st.divider()
    st.markdown(f"### 📊 평가 스코어 카드 (`{evaluator_mode}` 관점 / `{fb_title}`)")
    
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("📕 학업역량", f"{scores.get('academic', 0)} / 40 점")
    col_s2.metric("📗 진로역량", f"{scores.get('career', 0)} / 40 점")
    col_s3.metric("📘 공동체역량", f"{scores.get('community', 0)} / 20 점")
    col_s4.metric("✨ 최종 종합 점수", f"{scores.get('total', 0)} / 100 점")
    
    st.divider()
    
    # 📌 교사 전용 피드백 출력
    if "teacher_feedback" in res:
        st.subheader(f"👩‍🏫 NEIS 및 진학 지도용 교사전용 피드백 (`{fb_title}`)")
        tf = res["teacher_feedback"]
        st.success(f"**👍 핵심 장점:** {tf.get('strength', '')}")
        st.warning(f"**⚠️ 보완점 및 감점 사유:** {tf.get('weakness', '')}")
        if tf.get('quote'):
            st.info(f"**🎯 원문 인용 근거:** \"{tf.get('quote')}\"")

    # 📌 학생 전용 피드백 출력
    if "student_feedback" in res:
        st.subheader("🎓 학생 전용 쓴소리 진단 및 탐구 솔루션 리포트")
        sf = res["student_feedback"]
        
        st.markdown("#### 🔍 1. 입학사정관 관점의 냉정한 현재 위치 (지원 가능 대학 라인)")
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
    
    # --- 10. PDF / TXT 다운로드 기능 ---
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
                use_container_width=True
            )
        else:
            st.warning("ReportLab 모듈이 누락되었습니다. (`pip install reportlab` 필요)")
            
    with d2:
        txt_content = f"=== 브니엘고 AI 생기부 평가 리포트 ({evaluator_mode}) ===\n"
        txt_content += f"평가 모드: {fb_title}\n\n"
        txt_content += f"종합 점수: {scores.get('total', 0)} / 100\n"
        txt_content += f"- 학업역량: {scores.get('academic', 0)}/40\n"
        txt_content += f"- 진로역량: {scores.get('career', 0)}/40\n"
        txt_content += f"- 공동체역량: {scores.get('community', 0)}/20\n\n"
        
        if "teacher_feedback" in res:
            tf = res["teacher_feedback"]
            txt_content += f"[교사 피드백 장점]\n{tf.get('strength', '')}\n\n"
            txt_content += f"[교사 피드백 보완점]\n{tf.get('weakness', '')}\n\n"
        if "student_feedback" in res:
            sf = res["student_feedback"]
            txt_content += f"[학생 현위치 진단]\n{sf.get('current_position', '')}\n\n"
            txt_content += f"[추천 탐구 주제 솔루션]\n{sf.get('recommendation', '')}\n"
            
        st.download_button(
            label="📝 간이 리포트 TXT 다운로드",
            data=txt_content,
            file_name="생기부_평가_요약.txt",
            use_container_width=True
        )
