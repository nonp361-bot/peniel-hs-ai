import streamlit as st
import google.generativeai as genai
import pypdf
import json
import os
import urllib.request
from io import BytesIO

# --- ReportLab PDF 라이브러리 예외 처리 ---
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

# --- 2. 대학별 입시요강 가이드라인 보관 폴더 ---
CRITERIA_DB_DIR = "criteria_database"
os.makedirs(CRITERIA_DB_DIR, exist_ok=True)

# --- 3. 사이트 헤더 및 안내 ---
st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🏫 브니엘고등학교 AI 생기부 정밀 평가 시스템</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #4B5563;'>2028학년도 대입 개편안(2022 개정 교육과정) 및 Bloom 6단계 인지 수준 추적 엔진 적용</p>", unsafe_allow_html=True)
st.divider()

# --- 4. 사이드바 설정 ---
st.sidebar.markdown("### 🎓 평가자 모드 선택")
evaluator_mode = st.sidebar.radio(
    "입학사정관 유형을 선택하세요.",
    ["인서울 입학사정관", "지거국 입학사정관"],
    help="선택한 입학사정관 관점에 맞춰 학업 심화성, 전문교과 이수, 성실성 및 지역 적합성 등의 평가 비중과 피드백 톤이 달라집니다."
)

st.sidebar.divider()

# API 키 인증
api_key = ""
if os.path.exists("api_key.txt"):
    try:
        with open("api_key.txt", "r", encoding="utf-8") as f:
            api_key = f.read().strip()
    except Exception:
        pass

if not api_key:
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

if not api_key:
    api_key = st.sidebar.text_input("🔑 구글 Gemini API 키 입력", type="password")
    if api_key:
        genai.configure(api_key=api_key)
        st.sidebar.success("API 키 인증 완료")
    else:
        st.sidebar.warning("Gemini API 키를 입력해주세요.")
else:
    genai.configure(api_key=api_key)
    st.sidebar.success("🔑 API 키 자동 인증 완료")

st.sidebar.divider()

# AI 모델 선택
model_option = st.sidebar.selectbox(
    "🤖 Gemini 모델 선택",
    ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    index=0
)

st.sidebar.divider()

# 입시요강 관리 파일 업로더
st.sidebar.markdown("### ⚙️ 대학별 채점 기준 파일 관리")
uploaded_criteria = st.sidebar.file_uploader(
    "채점 기준 PDF/TXT 업로드",
    type=["pdf", "txt"],
    accept_multiple_files=True,
    key="criteria_uploader"
)

if uploaded_criteria:
    for file in uploaded_criteria:
        dest_path = os.path.join(CRITERIA_DB_DIR, file.name)
        if not os.path.exists(dest_path):
            with open(dest_path, "wb") as f:
                f.write(file.getbuffer())
    st.sidebar.success("💾 채점 기준 파일 저장 완료!")
    st.rerun()

accumulated_files = os.listdir(CRITERIA_DB_DIR)
selected_criteria_files = []

if accumulated_files:
    st.sidebar.markdown("**📌 반영할 채점 기준 선택**")
    for file_name in accumulated_files:
        if st.sidebar.checkbox(file_name, value=True, key=f"check_{file_name}"):
            selected_criteria_files.append(file_name)
    
    if st.sidebar.button("🗑️ 선택한 기준 파일 삭제", type="secondary"):
        for file_name in accumulated_files:
            if f"check_{file_name}" in st.session_state and st.session_state[f"check_{file_name}"]:
                os.remove(os.path.join(CRITERIA_DB_DIR, file_name))
        st.rerun()

# --- 5. 텍스트 추출 및 한글 폰트 관련 함수 ---
def extract_text_from_pdf(pdf_file):
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
        st.error(f"PDF 파일 읽기 오류: {e}")
        return ""

def load_local_file_text(filename):
    path = os.path.join(CRITERIA_DB_DIR, filename)
    if not os.path.exists(path):
        return ""
    if filename.endswith(".pdf"):
        return extract_text_from_pdf(path)
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="cp949") as f:
                return f.read()

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

# --- 6. 실시간 메인 화면 채점 기준표 분석 및 생성 함수 ---
@st.cache_data(show_spinner=False)
def generate_dynamic_criteria_summary(files_tuple, mode, model_name, api_key_val):
    if not api_key_val:
        return None
    genai.configure(api_key=api_key_val)
    combined_criteria_text = ""
    for fname in files_tuple:
        combined_criteria_text += f"\n--- [{fname}] ---\n" + load_local_file_text(fname)
    
    prompt = f"""
    당신은 대학 입학사정관입니다. 업로드된 채점 기준문서들을 분석하여 메인 화면에 상시 노출할 '실시간 생기부 채점 기준표'를 JSON 형식으로 작성하세요.
    
    [평가자 모드]: {mode}
    [기본 배점 구조 고정]:
    1. 학업역량 (40점)
    2. 진로역량 (40점)
    3. 공동체역량 (20점)
    
    [채점 기준 참고 문서 텍스트]:
    {combined_criteria_text if combined_criteria_text else "기본 2028학년도 대입 학종 범용 평가 가이드라인 적용"}

    응답은 오직 아래 JSON 형식으로만 작성하세요 (마크다운 기호 금지):
    {{
        "academic": {{
            "title": "I. 학업역량 (40점 만점)",
            "sub_items": [
                {{"item": "성취도 분포 및 이수환경", "score": 15, "desc": "주요 과목 성취도 및 전문교과 내 상대적 위치"}},
                {{"item": "학업태도 및 탐구의지", "score": 10, "desc": "교사 관찰 행동 근거 및 어려움 극복 서사"}},
                {{"item": "디지털 리터러시 & 비판적 탐구", "score": 15, "desc": "Bloom 5-6단계 사고 및 AI/데이터 비판적 활용"}}
            ]
        }},
        "career": {{
            "title": "II. 진로역량 (40점 만점)",
            "sub_items": [
                {{"item": "전공 관련 교과 이수 노력", "score": 10, "desc": "위계적 과목 선택 및 선택 동기"}},
                {{"item": "전공 관련 교과 성취도", "score": 10, "desc": "전공 과목 성취도의 차별성 및 전공적 사고"}},
                {{"item": "진로 탐색 활동과 경험", "score": 20, "desc": "교과-창체 연계 진로 에피소드 및 문헌 비판적 독해"}}
            ]
        }},
        "community": {{
            "title": "III. 공동체역량 (20점 만점)",
            "sub_items": [
                {{"item": "협업과 소통능력", "score": 6, "desc": "구체적 역할 기여 및 다원적 환경에서의 조율"}},
                {{"item": "나눔과 배려", "score": 4, "desc": "특정 대상을 도운 구체적 행동 사례"}},
                {{"item": "성실성과 규칙 준수", "score": 5, "desc": "출결 성실성 및 행동 특성 근거"}},
                {{"item": "리더십", "score": 5, "desc": "과정 중심 조율 서사 및 자발적 주도성"}}
            ]
        }}
    }}
    """
    try:
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt)
        cleaned = res.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return None

# --- 7. 메인 화면 상단: 실시간 채점 기준표 표시 ---
st.markdown(f"### 📋 메인 실시간 채점 기준표 (`{evaluator_mode}` 모드)")

if selected_criteria_files and api_key:
    criteria_json = generate_dynamic_criteria_summary(tuple(selected_criteria_files), evaluator_mode, model_option, api_key)
    if criteria_json:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**{criteria_json['academic']['title']}**")
            for sub in criteria_json['academic']['sub_items']:
                st.markdown(f"- **{sub['item']} ({sub['score']}점)**: {sub['desc']}")
        with col2:
            st.success(f"**{criteria_json['career']['title']}**")
            for sub in criteria_json['career']['sub_items']:
                st.markdown(f"- **{sub['item']} ({sub['score']}점)**: {sub['desc']}")
        with col3:
            st.warning(f"**{criteria_json['community']['title']}**")
            for sub in criteria_json['community']['sub_items']:
                st.markdown(f"- **{sub['item']} ({sub['score']}점)**: {sub['desc']}")
    else:
        st.info("💡 기본 채점 기준 [학업역량(40) / 진로역량(40) / 공동체역량(20)]이 적용됩니다.")
else:
    st.info("💡 사이드바에서 대학교 입시요강 가이드라인(PDF/TXT)을 업로드하고 선택하면, AI가 분석한 맞춤형 세부 채점 기준표가 실시간 반영됩니다.")

st.divider()

# --- 8. PDF 리포트 생성 함수 (ReportLab 연동) ---
def generate_pdf_report(result, student_filename, mode):
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
    
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontName=font_name, fontSize=15, leading=19, textColor=colors.HexColor('#1E3A8A'), alignment=1, spaceAfter=10)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName=font_name, fontSize=8.5, leading=11, textColor=colors.HexColor('#4B5563'), alignment=1, spaceAfter=12)
    h1_style = ParagraphStyle('H1', parent=styles['Heading2'], fontName=font_name, fontSize=11, leading=14, textColor=colors.HexColor('#1E3A8A'), spaceBefore=10, spaceAfter=5, keepWithNext=True)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName=font_name, fontSize=8, leading=11, textColor=colors.HexColor('#1F2937'), spaceAfter=3)
    
    def create_box(text, bg_color, border_color, text_color):
        inner_style = ParagraphStyle('BoxInner', fontName=font_name, fontSize=7.5, leading=10.5, textColor=colors.HexColor(text_color))
        p = Paragraph(text, inner_style)
        t = Table([[p]], colWidths=[520])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(bg_color)),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor(border_color)),
            ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))
        return t

    story = []
    story.append(Paragraph(f"🎓 브니엘고등학교 AI 생기부 정밀 진단 보고서 ({mode} 모드)", title_style))
    story.append(Paragraph(f"학생 파일: {student_filename}  |  평가 방식: 2028학년도 대입 표준 및 Bloom 6단계/AI 오염도 감리 적용", subtitle_style))
    story.append(Spacer(1, 5))
    
    story.append(Paragraph("📊 100점 만점 영역별 스코어 카드", h1_style))
    
    scores = result.get("scores", {})
    table_data = [
        [Paragraph("<b>평가 영역</b>", body_style), Paragraph("<b>세부 평가 항목</b>", body_style), Paragraph("<b>취득 점수</b>", body_style)],
        [Paragraph("I. 학업역량 (40점)", body_style), Paragraph("성취도 분포 / 학업태도 / 디지털 리터러시", body_style), Paragraph(f"<b>{scores.get('academic_total', '0')} / 40</b>", body_style)],
        [Paragraph("II. 진로역량 (40점)", body_style), Paragraph("전공 이수 노력 / 전공 성취도 / 진로 탐색 경험", body_style), Paragraph(f"<b>{scores.get('career_total', '0')} / 40</b>", body_style)],
        [Paragraph("III. 공동체역량 (20점)", body_style), Paragraph("협업·소통 / 나눔·배려 / 성실성 / 리더십", body_style), Paragraph(f"<b>{scores.get('community_total', '0')} / 20</b>", body_style)],
        [Paragraph("<b>✨ 종합 총점</b>", body_style), Paragraph("<b>모든 영역 합산 환산점수</b>", body_style), Paragraph(f"<b><font color='#EF4444'>{scores.get('grand_total', '0')} / 100</font></b>", body_style)]
    ]
    
    t_score = Table(table_data, colWidths=[120, 280, 120])
    t_score.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('BACKGROUND', (0,4), (-1,4), colors.HexColor('#FEF2F2')),
    ]))
    story.append(t_score)
    story.append(Spacer(1, 10))
    
    # 교사용 피드백
    story.append(Paragraph("👩‍🏫 [교사용 정밀 피드백]", h1_style))
    teacher_fb = result.get("teacher_feedback", {})
    
    sections = [
        ("1. 과목세부능력 및 특기사항 전용", teacher_fb.get("setuk", {})),
        ("2. 동아리 특기사항 전용", teacher_fb.get("club", {})),
        ("3. 자율 및 진로 특기사항 전용", teacher_fb.get("autonomy_career", {})),
        ("4. 행동특성 및 종합의견 전용", teacher_fb.get("behavior", {})),
        ("5. 생기부 종합 전용 피드백", teacher_fb.get("overall", {})),
    ]
    
    for title, content in sections:
        story.append(Paragraph(f"<b>[{title}]</b>", body_style))
        story.append(Paragraph(f"• <b>장점:</b> {content.get('strength', '내용 없음')}", body_style))
        story.append(Paragraph(f"• <b>보완점:</b> {content.get('weakness', '내용 없음')}", body_style))
        if content.get('quote'):
            story.append(create_box(f"<b>인용 근거:</b> {content['quote']}", '#FEF3C7', '#F59E0B', '#451A03'))
        story.append(Spacer(1, 4))
        
    story.append(PageBreak())
    
    # 학생용 피드백
    story.append(Paragraph("🎓 [학생용 냉정한 현위치 진단 & 솔루션]", h1_style))
    student_fb = result.get("student_feedback", {})
    
    story.append(Paragraph("<b>1. 현재 위치 냉정 진단 (지원 가능 대학 라인)</b>", body_style))
    story.append(create_box(student_fb.get("current_position", "진단 내용 없음"), '#F3F4F6', '#9CA3AF', '#111827'))
    story.append(Spacer(1, 6))
    
    story.append(Paragraph("<b>2. 활동 강점 & 치명적 보완점</b>", body_style))
    story.append(Paragraph(f"• <b>강점:</b> {student_fb.get('strength_analysis', '')}", body_style))
    story.append(Paragraph(f"• <b>치명적 약점:</b> {student_fb.get('weakness_analysis', '')}", body_style))
    story.append(Spacer(1, 6))
    
    story.append(Paragraph("<b>3. 앞으로의 구체적 추천 활동 및 탐구 주제 솔루션</b>", body_style))
    story.append(create_box(student_fb.get("recommendation", "솔루션 내용 없음"), '#FEF2F2', '#EF4444', '#991B1B'))
    
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

# --- 9. 생기부 업로드 및 평가 실행 구역 ---
st.markdown("### 📂 생기부 PDF 제출 및 AI 평가")
st.info("🔒 제출된 파일은 서버나 디스크에 저장되지 않고, 분석 즉시 휘발성 메모리(RAM)에서 완전 삭제됩니다.")

student_pdf = st.file_uploader("학생의 학교생활기록부 PDF 파일을 업로드하세요.", type=["pdf"], key="student_pdf_uploader")

if student_pdf and api_key:
    st.success(f"📎 파일 로드 완료: {student_pdf.name}")
    
    if st.button("🔥 AI 사정관 정밀 평가 시작하기", type="primary", use_container_width=True):
        with st.spinner("🧠 AI 입학사정관이 2028 대입 가이드라인 및 Bloom 6단계 사고 수준을 바탕으로 생기부를 정밀 검증 중입니다..."):
            
            # RAM 상에서 직접 텍스트 추출 (휘발성)
            student_text = extract_text_from_pdf(student_pdf)
            
            if not student_text.strip():
                st.error("❌ PDF 파일에서 텍스트를 추출할 수 없습니다.")
                st.stop()
                
            # 기준 텍스트 병합
            combined_criteria = ""
            if selected_criteria_files:
                for fname in selected_criteria_files:
                    combined_criteria += f"\n--- [{fname}] ---\n" + load_local_file_text(fname)
            else:
                combined_criteria = "2028 대입 표준 학종 평가 지표 적용"

            # AI 프롬프트 생성
            prompt = f"""
            당신은 전국 대학부종합전형 서류를 평가하는 [{evaluator_mode}]입니다.
            제공된 [학생 생기부 텍스트]를 분석하여 점수와 정밀 피드백을 산출하세요.
            
            [평가 지침 및 감점 규칙]:
            1. 인서울/지거국 평가자 모드('{evaluator_mode}')의 특성을 철저히 반영할 것.
            2. 학업역량(40점), 진로역량(40점), 공동체역량(20점) 총 100점 만점으로 점수를 매기세요.
            3. Bloom의 인지 수준 6단계를 적용하여 단순 조사/요약(1-2단계)은 중간 이하 감점 처리, 비판적 검토 및 대안 제안(5-6단계)만 영역별 고득점을 부여하세요.
            4. 교사 관찰 부재 및 AI 대필 템플릿 문구는 엄격히 감점 사유로 지적하세요.
            5. 피드백은 [교사용 5개 영역]과 [학생용 1개 영역]으로 엄격히 분리하여 작성하세요.
            6. 학생용 피드백은 헛된 희망을 주지 않고 입학사정관 관점의 냉정한 현재 위치 진단과 치명적 약점, 앞으로 보완할 구체적 탐구 주제를 제시하세요.

            [채점 기준 참고 자료]:
            {combined_criteria}

            [학생 생기부 텍스트]:
            {student_text}

            반드시 아래 지정된 JSON 형식으로만 순수 텍스트로 응답하세요 (마크다운 기호 금지):
            {{
                "scores": {{
                    "academic_total": 32.5,
                    "career_total": 31.0,
                    "community_total": 17.5,
                    "grand_total": 81.0
                }},
                "teacher_feedback": {{
                    "setuk": {{
                        "strength": "과목 세특의 장점 서술",
                        "weakness": "과목 세특의 보완점 및 감점 사유 (Bloom단계, AI 의심문장 지적)",
                        "quote": "세특 원문 문장 인용"
                    }},
                    "club": {{
                        "strength": "동아리 활동 장점",
                        "weakness": "동아리 활동 보완점",
                        "quote": "동아리 원문 인용"
                    }},
                    "autonomy_career": {{
                        "strength": "자율 및 진로 활동 장점",
                        "weakness": "자율 및 진로 활동 보완점",
                        "quote": "원문 인용"
                    }},
                    "behavior": {{
                        "strength": "행동특성 및 종합의견 장점",
                        "weakness": "행특 보완점",
                        "quote": "행특 원문 인용"
                    }},
                    "overall": {{
                        "strength": "생기부 전체의 일관성 및 성장 서사 장점",
                        "weakness": "생기부 전체 종합 보완점",
                        "quote": "주요 원문 인용"
                    }}
                }},
                "student_feedback": {{
                    "current_position": "입학사정관 관점의 냉정한 현재 위치 및 지원 가능 대학 라인 진단",
                    "strength_analysis": "여태까지 했던 활동의 핵심 강점 분석",
                    "weakness_analysis": "치명적인 보완점 및 감점 요소 분석",
                    "recommendation": "앞으로 3학년/다음 학기에 실행해야 할 구체적인 탐구 주제 및 과목 선택/활동 제언 솔루션"
                }}
            }}
            """
            
            try:
                model = genai.GenerativeModel(model_option)
                response = model.generate_content(prompt)
                cleaned_res = response.text.strip().replace("```json", "").replace("```", "").strip()
                result_data = json.loads(cleaned_res)
                
                st.session_state["eval_result"] = result_data
                st.session_state["pdf_filename"] = student_pdf.name
                st.success("🎉 분석 완료! 개인정보 보호를 위해 제출된 생기부 원본 데이터는 메모리에서 즉시 영구 파기되었습니다.")
            except json.JSONDecodeError:
                st.error("⚠️ AI 응답을 해석하는 중 오류가 발생했습니다. 다시 시도해 주세요.")
                st.code(response.text)
            except Exception as e:
                st.error(f"평가 도중 오류 발생: {e}")

# --- 10. 평가 결과 출력 구역 (교사용 탭 vs 학생용 탭) ---
if "eval_result" in st.session_state:
    res = st.session_state["eval_result"]
    scores = res.get("scores", {})
    
    st.divider()
    st.markdown(f"### 📊 평가 결과 스코어 카드 (`{evaluator_mode}`)")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📕 학업역량", f"{scores.get('academic_total', 0)} / 40 점")
    m2.metric("📗 진로역량", f"{scores.get('career_total', 0)} / 40 점")
    m3.metric("📘 공동체역량", f"{scores.get('community_total', 0)} / 20 점")
    m4.metric("✨ 종합 총점", f"{scores.get('grand_total', 0)} / 100 점")
    
    st.divider()
    
    main_tab1, main_tab2 = st.tabs(["👩‍🏫 교사용 정밀 피드백 (항목별 장점/보완점)", "🎓 학생용 냉정한 현위치 진단 & 솔루션"])
    
    # 📌 [교사용 피드백] (5개 전용 탭)
    with main_tab1:
        st.subheader("👩‍🏫 NEIS 기재 및 지도용 교사 전용 피드백")
        t_tab1, t_tab2, t_tab3, t_tab4, t_tab5 = st.tabs([
            "1. 과목세특 피드백",
            "2. 동아리 피드백",
            "3. 자율·진로 피드백",
            "4. 행특 피드백",
            "5. 생기부 종합 피드백"
        ])
        
        teacher_data = res.get("teacher_feedback", {})
        
        def display_teacher_item(data_dict, title):
            st.markdown(f"#### 📌 {title}")
            st.success(f"**👍 장점:** {data_dict.get('strength', '')}")
            st.warning(f"**⚠️ 보완점 및 감점 사유:** {data_dict.get('weakness', '')}")
            if data_dict.get('quote'):
                st.info(f"**🎯 인용 원문 근거:** \"{data_dict.get('quote')}\"")

        with t_tab1:
            display_teacher_item(teacher_data.get("setuk", {}), "과목 세부능력 및 특기사항")
        with t_tab2:
            display_teacher_item(teacher_data.get("club", {}), "동아리 활동 특기사항")
        with t_tab3:
            display_teacher_item(teacher_data.get("autonomy_career", {}), "자율 및 진로 활동 특기사항")
        with t_tab4:
            display_teacher_item(teacher_data.get("behavior", {}), "행동특성 및 종합의견")
        with t_tab5:
            display_teacher_item(teacher_data.get("overall", {}), "생기부 전체 종합 서사")

    # 📌 [학생용 피드백] (1개 단일 탭)
    with main_tab2:
        st.subheader("🎓 학생 전용 쓴소리 진단 리포트")
        student_data = res.get("student_feedback", {})
        
        st.markdown("#### 🔍 1. 입학사정관 관점의 냉정한 현재 위치 진단")
        st.error(student_data.get("current_position", ""))
        
        col_st1, col_st2 = st.columns(2)
        with col_st1:
            st.markdown("#### 👍 2. 여태까지 했던 활동의 강점")
            st.success(student_data.get("strength_analysis", ""))
        with col_st2:
            st.markdown("#### 🚨 3. 치명적인 약점 및 보완점")
            st.warning(student_data.get("weakness_analysis", ""))
            
        st.markdown("#### 🚀 4. 향후 추천 활동 및 구체적 탐구 주제 솔루션")
        st.info(student_data.get("recommendation", ""))

    st.divider()
    
    # --- 11. PDF/TXT 보고서 다운로드 ---
    st.markdown("### 📥 3단계: 채점 보고서 다운로드")
    d_col1, d_col2 = st.columns(2)
    
    with d_col1:
        if REPORTLAB_AVAILABLE:
            pdf_bytes = generate_pdf_report(res, st.session_state.get("pdf_filename", "student.pdf"), evaluator_mode)
            st.download_button(
                label="📄 정밀 진단 보고서 PDF 다운로드",
                data=pdf_bytes,
                file_name=f"브니엘고_AI_생기부평가_{evaluator_mode}_{st.session_state.get('pdf_filename', 'student').replace('.pdf','')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        else:
            st.warning("ReportLab 모듈이 설치되어 있지 않습니다. (`pip install reportlab` 필요)")
            
    with d_col2:
        txt_report = f"=== 브니엘고 AI 생기부 평가 리포트 ({evaluator_mode}) ===\n\n"
        txt_report += f"종합 점수: {scores.get('grand_total', 0)} / 100\n"
        txt_report += f"- 학업역량: {scores.get('academic_total', 0)}/40\n"
        txt_report += f"- 진로역량: {scores.get('career_total', 0)}/40\n"
        txt_report += f"- 공동체역량: {scores.get('community_total', 0)}/20\n\n"
        txt_report += f"[학생 현재 위치 진단]\n{student_data.get('current_position', '')}\n\n"
        txt_report += f"[향후 추천 탐구 주제]\n{student_data.get('recommendation', '')}\n"
        
        st.download_button(
            label="📝 간이 리포트 TXT 다운로드",
            data=txt_report,
            file_name="생기부_평가_요약.txt",
            use_container_width=True
        )
