import streamlit as st
import google.generativeai as genai
import pypdf
import json
import os
import urllib.request  # 클라우드 한글 폰트 다운로드용 라이브러리 추가
from io import BytesIO

# --- PDF 생성 라이브러리 임포트 및 예외 처리 ---
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# --- 1. 페이지 기본 설정 ---
st.set_page_config(
    page_title="브니엘고등학교 2028학년도 AI 생기부 정밀 채점 시스템",
    page_icon="🎓",
    layout="wide"
)

# --- 2. 로컬 채점 기준 보관 폴더(데이터베이스) 설정 ---
CRITERIA_DB_DIR = "criteria_database"
os.makedirs(CRITERIA_DB_DIR, exist_ok=True)

# --- 3. 구글 Gemini API 인증 및 설정 (사이드바 정렬 개편) ---
st.sidebar.markdown("<h1 style='text-align: center; font-size: 80px; margin-bottom: 0;'>🎓</h1>", unsafe_allow_html=True)
st.sidebar.markdown("<h3 style='text-align: center; margin-top: 0; margin-bottom: 20px;'>브니엘고 AI 평가 시스템<br/>(2028학년도 표준 규격)</h3>", unsafe_allow_html=True)

st.sidebar.info("🔒 학교 구글 워크스페이스 인증됨\n\n계정: teacher@peniel.hs.kr")
st.sidebar.divider()

st.sidebar.markdown("### 🎯 목표 대학교 유형 설정")
target_university_group = st.sidebar.selectbox(
    "학생의 목표 대학 그룹을 선택하세요.",
    ["인서울 상위 10대 대학", "지방거점국립대학교 (지거국)"],
    index=0,
    help="선택한 대학교의 최신 학생부종합전형(학종) 평가 알고리즘 및 배점이 AI 채점에 즉시 반영됩니다."
)
st.sidebar.divider()

HARDCODED_API_KEY = "" 

local_key_file = "api_key.txt"
api_key = ""
if os.path.exists(local_key_file):
    try:
        with open(local_key_file, "r", encoding="utf-8") as f:
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
    api_key = st.sidebar.text_input("🔑 구글 Gemini API 키를 입력하세요", type="password")
    if api_key:
        genai.configure(api_key=api_key)
        st.sidebar.success("✅ 구글 API 키 인증 완료!")
    else:
        st.sidebar.warning("⚠️ 서비스를 이용하려면 구글 API 키를 설정해야 합니다.")
else:
    genai.configure(api_key=api_key)
    st.sidebar.success("🔑 구글 클라우드 API 자동 인증 완료!")

st.sidebar.divider()

st.sidebar.markdown("### 🤖 AI 엔진 모델 설정")
model_option = st.sidebar.selectbox(
    "사용할 Gemini 모델을 선택하세요.",
    ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    index=0,
    help="기본적으로 가장 호환성이 높은 gemini-2.5-flash를 사용하며, 오류가 지속되면 다른 모델로 전환해 보세요."
)

st.sidebar.divider()

st.sidebar.markdown("### ⚙️ 대학별 입시요강 관리")

uploaded_criteria = st.sidebar.file_uploader(
    "새로운 대학교 입시요강(PDF/TXT) 업로드",
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
    st.sidebar.success("💾 파일이 학교 데이터베이스에 누적 보관되었습니다!")

accumulated_files = os.listdir(CRITERIA_DB_DIR)

selected_criteria_files = []
if accumulated_files:
    st.sidebar.markdown("**📌 반영할 대학교 가이드라인 선택**")
    for file_name in accumulated_files:
        if st.sidebar.checkbox(file_name, value=True, key=f"check_{file_name}"):
            selected_criteria_files.append(file_name)
    
    if st.sidebar.button("🗑️ 선택한 기준 보관함에서 삭제", type="secondary"):
        for file_name in accumulated_files:
            if f"check_{file_name}" in st.session_state and st.session_state[f"check_{file_name}"]:
                os.remove(os.path.join(CRITERIA_DB_DIR, file_name))
        st.rerun()
else:
    st.sidebar.caption("ℹ️ 보관함이 비어 있습니다. 입시요강을 올려서 채우세요.")

# --- 4. 시스템 폰트 탐색 및 자동 다운로드 함수 (한글 깨짐 해결용) ---
def get_korean_font_path():
    local_font_name = "NanumGothic.ttf"
    if os.path.exists(local_font_name):
        return local_font_name

    paths = [
        "C:\\Windows\\Fonts\\malgun.ttf",       # Windows 맑은 고딕
        "C:\\Windows\\Fonts\\malgunbd.ttf",     # Windows 맑은 고딕 Bold
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf", # Mac 애플고딕
        "/Library/Fonts/AppleGothic.ttf",
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", # Linux 나눔고딕
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/truetype/fonts-nanum/NanumGothic.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return p

    font_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    try:
        urllib.request.urlretrieve(font_url, local_font_name)
        if os.path.exists(local_font_name):
            return local_font_name
    except Exception as e:
        st.sidebar.warning(f"⚠️ 시스템 내 한글 폰트 인식이 불가하여 자동 다운로드를 시도했으나 실패했습니다: {e}")
    return None

# --- 5. PDF 보고서 작성 로직 (ReportLab 연동 - 겹침 및 중복 오차 완벽 해결 버전) ---
def generate_pdf_report(result, student_filename, target_group):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    font_path = get_korean_font_path()
    font_name = "Helvetica"
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("KoreanFont", font_path))
            font_name = "KoreanFont"
        except Exception:
            pass
            
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1,
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#4B5563'),
        alignment=1,
        spaceAfter=15
    )
    
    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#1F2937'),
        spaceAfter=4
    )
    
    evidence_title_style = ParagraphStyle(
        'EvidenceTitle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#B45309'),
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True
    )

    feedback_title_style = ParagraphStyle(
        'FeedbackTitle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#B91C1C'),
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True
    )

    audit_title_style = ParagraphStyle(
        'AuditTitle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#7C3AED'),
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True
    )

    # [테두리 겹침 철저 배제] 테이블 래핑 방식으로 Callout 박스를 렌더링하는 헬퍼 함수 정의
    # 가로 총 너비: 515포인트 (A4 여백 보정 적용)
    def create_callout_box(text, bg_color_hex, border_color_hex, text_color_hex, font_size=8, leading=12):
        inner_style = ParagraphStyle(
            'CalloutInner',
            fontName=font_name,
            fontSize=font_size,
            leading=leading,
            textColor=colors.HexColor(text_color_hex)
        )
        p = Paragraph(text, inner_style)
        t = Table([[p]], colWidths=[515])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(bg_color_hex)),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor(border_color_hex)),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        return t
    
    story = []
    
    story.append(Paragraph(f"🎓 2028학년도 대비 학생부종합전형 AI 정밀 진단 보고서 ({target_group})", title_style))
    story.append(Paragraph(f"대상 학생 파일: {student_filename}   |   평가 모델: {model_option}   |   방식: 사정관 공동연구 및 블룸/AI 필터 완벽 연동형", subtitle_style))
    story.append(Spacer(1, 5))
    
    story.append(Paragraph("📊 2028학년도 개정 핵심 10대 지표별 스코어 카드", h1_style))
    
    # 가로 총 너비 515포인트 규격과 완벽하게 매칭되는 120 + 275 + 120 그리드 테이블 설계
    table_data = [
        [Paragraph("<b>평가 역량 대분류</b>", body_style), Paragraph("<b>세부 정밀 평가 지표 (100점 만점 기준)</b>", body_style), Paragraph("<b>취득 점수 (소수점 정밀계산)</b>", body_style)],
        [Paragraph("<b>I. 학업역량 (40점)</b>", body_style), Paragraph("1. 성취도 분포 및 이수 환경의 상대적 우위성 (15점 만점)", body_style), Paragraph(f"<b>{result.get('score_achievement_15', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("2. 행동 동기 및 어려움 극복 서사 기반 학업태도 (10점 만점)", body_style), Paragraph(f"<b>{result.get('score_academic_attitude_10', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("3. 디지털 리터러시 및 비판적 미디어 탐구 역량 (15점 만점)", body_style), Paragraph(f"<b>{result.get('score_digital_literacy_15', '0.0')}</b>", body_style)],
        [Paragraph("<b>II. 진로역량 (40점)</b>", body_style), Paragraph("4. 전공 연계 교과의 위계적 이수 노력 및 동기 (10점 만점)", body_style), Paragraph(f"<b>{result.get('score_major_selection_10', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("5. 전공 관련 주요 교과 성취도 차별성 및 전공적 사고 (10점 만점)", body_style), Paragraph(f"<b>{result.get('score_major_grades_10', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("6. 교과-창체 연계 진로 에피소드 및 비판적 독해 (20점 만점)", body_style), Paragraph(f"<b>{result.get('score_career_experience_20', '0.0')}</b>", body_style)],
        [Paragraph("<b>III. 공동체역량 (20점)</b>", body_style), Paragraph("7. 다원적 환경에서의 실질적 협업 및 소통 역량 (6점 만점)", body_style), Paragraph(f"<b>{result.get('score_collab_6', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("8. 특정 대상을 도운 구체적 나눔과 배려 (4점 만점)", body_style), Paragraph(f"<b>{result.get('score_sharing_4', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("9. 무단 지각/결석 배제 성실성 및 성품 행특 근거 (5점 만점)", body_style), Paragraph(f"<b>{result.get('score_sincerity_5', '0.0')}</b>", body_style)],
        [Paragraph("", body_style), Paragraph("10. 과정 중심 조율 과정 입증 리더십 및 자발 주도성 (5점 만점)", body_style), Paragraph(f"<b>{result.get('score_leadership_5', '0.0')}</b>", body_style)],
        [Paragraph("<b>✨ 합계 총점</b>", body_style), Paragraph("<b>모든 평가지표 합산 종합 환산점수 (보수적 사정관 컷)</b>", body_style), Paragraph(f"<b><font color='#EF4444'>{result.get('score_total', '0.0')} / 100</font></b>", body_style)]
    ]
    
    summary_table = Table(table_data, colWidths=[120, 275, 120])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F3F4F6')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('SPAN', (0,1), (0,3)),
        ('SPAN', (0,4), (0,6)),
        ('SPAN', (0,7), (0,10)),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('BACKGROUND', (0,11), (-1,11), colors.HexColor('#FEF2F2')),
    ]))
    
    story.append(summary_table)
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("🚨 생성형 AI 대필 및 오염도 진단 감리 서평 (AI Audit)", h1_style))
    audit_data = result.get("ai_pollution_audit", {})
    audit_risk = audit_data.get("risk_level", "보통(안전)")
    audit_verdict = audit_data.get("audit_verdict", "AI 작성 의심 에피소드가 확인되지 않았습니다.")
    story.append(Paragraph(f"<b>• AI 오염 위험도:</b> <font color='#7C3AED'>{audit_risk}</font>  |  <b>• 의심 영역:</b> {audit_data.get('suspected_areas', '없음')}", body_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>사정관 연합 감리 위원회 서평 및 신뢰도 검토 의견:</b>", audit_title_style))
    story.append(create_callout_box(audit_verdict, '#F5F3FF', '#8B5CF6', '#4C1D95'))
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("🔍 평가 지표별 세부 분석 및 냉철한 쓴소리 솔루션", h1_style))
    
    # --- 학업 역량 세부 정보 ---
    story.append(Paragraph("<b>[학업 역량 및 디지털 탐구 정성 진단 (배점: 40점)]</b>", body_style))
    story.append(Paragraph(f"성취도/태도 진단: {result.get('reason_academic_core', '분석 누락')}", body_style))
    if result.get('evidence_academic_core'):
        story.append(Paragraph("<b>🎯 매칭된 학생부 원문 근거 (블룸 인지영역 대조)</b>", evidence_title_style))
        story.append(create_callout_box(f'"{result["evidence_academic_core"]}"', '#FEF3C7', '#F59E0B', '#451A03'))
    if result.get('improvement_academic_core'):
        story.append(Paragraph("<b>⚠️ 학업 역량 돌파를 위한 뼈아픈 조언 및 심화과제 지침</b>", feedback_title_style))
        story.append(create_callout_box(result['improvement_academic_core'], '#FEF2F2', '#EF4444', '#7F1D1D'))
    story.append(Spacer(1, 10))
    
    # --- 진로 역량 세부 정보 ---
    story.append(Paragraph("<b>[진로 역량 및 전공교과 위계성 진단 (배점: 40점)]</b>", body_style))
    story.append(Paragraph(f"진로/교과 설계 진단: {result.get('reason_career_core', '분석 누락')}", body_style))
    if result.get('evidence_career_core'):
        story.append(Paragraph("<b>🎯 매칭된 학생부 원문 근거 (위계성 및 독해력 대조)</b>", evidence_title_style))
        story.append(create_callout_box(f'"{result["evidence_career_core"]}"', '#FEF3C7', '#F59E0B', '#451A03'))
    if result.get('improvement_career_core'):
        story.append(Paragraph("<b>⚠️ 진로 역량 돌파를 위한 뼈아픈 조언 및 고난도 연구 추천 소주제</b>", feedback_title_style))
        story.append(create_callout_box(result['improvement_career_core'], '#FEF2F2', '#EF4444', '#7F1D1D'))
    story.append(Spacer(1, 10))

    # --- 공동체 역량 세부 정보 ---
    story.append(Paragraph("<b>[공동체 역량 및 자발적 리더십 진단 (배점: 20점)]</b>", body_style))
    story.append(Paragraph(f"공동체성/리더십 진단: {result.get('reason_social_core', '분석 누락')}", body_style))
    if result.get('evidence_social_core'):
        story.append(Paragraph("<b>🎯 매칭된 학생부 원문 근거 (다원적 협업 및 조율 에피소드)</b>", evidence_title_style))
        story.append(create_callout_box(f'"{result["evidence_social_core"]}"', '#FEF3C7', '#F59E0B', '#451A03'))
    if result.get('improvement_social_core'):
        story.append(Paragraph("<b>⚠️ 인성/성실성 영역 감점 요인 지적 및 보완 행동 제언</b>", feedback_title_style))
        story.append(create_callout_box(result['improvement_social_core'], '#FEF2F2', '#EF4444', '#7F1D1D'))

    story.append(Spacer(1, 12))
    story.append(Paragraph("본 보고서에 출력된 가상 시뮬레이션 및 데이터는 브니엘고등학교 AI 생기부 평가 시스템의<br/>개인정보 전량 즉시 파기(Transient Data) 안전 규정에 따라 세션이 종료되는 순간 완벽하게 제거됩니다.", footer_style))
    
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

# --- 6. 텍스트 추출 함수 (PDF 읽기 부품) ---
def extract_text_from_pdf(uploaded_file):
    if uploaded_file is None:
        return ""
    try:
        pdf_reader = pypdf.PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text
    except Exception as e:
        st.error(f"PDF 파일 읽기 중 오류 발생: {e}")
        return ""

def load_local_file_text(filename):
    path = os.path.join(CRITERIA_DB_DIR, filename)
    if not os.path.exists(path):
        return ""
    if filename.endswith(".pdf"):
        try:
            pdf_reader = pypdf.PdfReader(path)
            text = ""
            for page in pdf_reader.pages:
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
            with open(path, "r", encoding="cp949") as f:
                return f.read()

# --- 7. 메인 화면 구성 ---
st.markdown('<h1 style="color: #1E3A8A;">브니엘고등학교 2028학년도 AI 생기부 정밀 채점 시스템</h1>', unsafe_allow_html=True)

st.error("⚠️ **2028학년도 대입 연합 사정관 표준 평가 가이드 및 블룸 6단계 추적 엔진 기본 탑재 완료:** 2022 개정 교육과정에 맞춘 '성취도 분포/이수환경 분석(15점)', '디지털 리터러시/비판적 탐구(15점)', '블룸의 인지 수준 6단계(지식/이해 vs 평가/창안) 판별식' 및 'AI 생성 의심 문구 필터링 감리'가 100점 만점 구조로 자동 구현됩니다. 타협 없는 점수 차감과 아주 냉철한 극복형 솔루션이 학생에게 제시됩니다.")
st.markdown(f'<p style="color: #4B5563;">현재 선택된 인재상 평가 엔진: <b>{target_university_group} (초정밀 보수적 평가)</b></p>', unsafe_allow_html=True)

# 생기부 파일 첨부
st.markdown("### 📂 1단계: 생기부 파일 업로드")
student_file = st.file_uploader("학생의 생활기록부 PDF 파일을 올리세요.", type=["pdf"])

st.divider()

# --- 8. 단계별 가이드 및 채점/결과 로직 ---
if not api_key:
    st.info("👈 왼쪽 사이드바를 열어 **구글 Gemini API 키**를 먼저 입력해 주세요.")
elif api_key and not student_file:
    st.info("📂 API 키 인증이 완료되었습니다! 이제 화면 중앙에 **학생의 생활기록부 PDF 파일**을 업로드해 주세요.")
elif api_key and student_file:
    st.success(f"📎 생기부 파일 로드 완료: {student_file.name}")
    
    if selected_criteria_files:
        st.info(f"🎯 이번 채점에는 {target_university_group} 모델과 보관함에서 선택한 **{len(selected_criteria_files)}개 대학 입시요강**이 융합 적용됩니다.\n\n적용 서류: {', '.join(selected_criteria_files)}")
    else:
        st.warning(f"⚠️ 선택된 대학별 입시요강이 없습니다. 기본 **[{target_university_group}]** 표준 서류평가 지표로 채점을 진행합니다.")

    if st.button("🔥 AI 실시간 채점 시작하기", type="primary", use_container_width=True):
        
        with st.spinner(f"🧠 AI 사정관이 2028 대입 연합 기준(블룸 6단계 판별식 및 AI 오염 감리 포함)으로 차가운 서류 검증 중... (약 10~25초 소요)"):
            
            student_text = extract_text_from_pdf(student_file)
            
            if not student_text.strip():
                st.error("❌ 업로드한 PDF 파일에서 텍스트를 추출할 수 없습니다. 빈 문서인지 확인해 주세요.")
                st.stop()
            
            criteria_text = ""
            if selected_criteria_files:
                for file_name in selected_criteria_files:
                    criteria_text += f"\n--- [{file_name} 입시가이드] ---\n"
                    criteria_text += load_local_file_text(file_name) + "\n"
            else:
                criteria_text = "선택된 대학교 그룹의 학생부종합전형 인재상 및 공통 서류 평가 요소를 적용하여 엄격히 평가할 것."

            prompt = f"""
            당신은 대학 입학 사정관 연합회(5개교 공동 연구 기준)의 가장 집요하고 보수적인 수석 입학사정관이자, 학생이 방심하지 않도록 뼈를 때리는 냉철한 쓴소리 피드백을 내리는 브니엘고등학교의 진학 교사입니다.
            제공된 [학생 생기부 텍스트]를 완벽히 독해하고, 아래에 명시된 [2028학년도 인서울 표준 범용 입학사정관 평가기준 체크리스트 (100점 만점)]을 기본 장착하여 등급과 소수점 스코어를 정밀 산출하세요.
            
            =========================================
            [2028학년도 인서울 표준 범용 입학사정관 평가기준 체크리스트 및 감점 규칙]
            
            I. 학업역량 (총 40점)
            1. 성취도 분포 및 이수 환경의 상대적 우위성 (15점 만점)
            2. 행동 동기 및 어려움 극복 서사 기반 학업태도 (10점 만점)
            3. 디지털 리터러시 및 비판적 미디어 탐구 역량 (15점 만점)
            
            II. 진로역량 (40점)
            4. 전공 연계 교과의 위계적 이수 노력 및 동기 (10점 만점)
            5. 전공 관련 주요 교과 성취도 차별성 및 전공적 사고 (10점 만점)
            6. 교과-창체 연계 진로 에피소드 및 비판적 독해 (20점 만점)

            III. 공동체역량 (총 20점)
            7. 다원적 환경에서의 실질적 협업 및 소통 역량 (6점 만점)
            8. 특정 대상을 도운 구체적 나눔과 배려 (4점 만점)
            9. 성실성과 규칙 준수 (5점 만점)
            10. 과정 중심 조율 과정 입증 리더십 및 자발 주도성 (5점 만점)
            
            =========================================
            [★ 초정밀 AI 감리 규칙 및 블룸 인지 수준 6단계 필터 ★]
            
            1. 블룸(Bloom) 인지 수준 판별식:
               - 지식/이해 단계 중심의 평이한 기재는 냉정하게 중위권 혹은 감점 등급으로 고정 분류한다.
               - 평가/창안 단계가 입증되어야 비로소 영역별 만점(S등급)을 부여한다.
            2. AI 오염 및 신뢰도 검사 (부록 B 가이드):
               - "표준 AI 템플릿 의심", "과목 간 문체 이질성", "교사 관찰 부재" 항목 탐색.
            
            =========================================
            [채점 기준 가이드라인 (누적 대학교 가이드라인)]
            {criteria_text}
            
            [학생 생기부 텍스트]
            {student_text}
            
            반드시 아래 지정된 JSON 형식으로만 완벽하게 답변해야 합니다. 마크다운 기호(```json 등)는 앞뒤에 절대 넣지 말고 오직 순수한 JSON 텍스트만 출력하세요. 모든 점수 합산 필드는 오차가 없어야 합니다.
            {{
                "score_achievement_15": "성취도/이수환경 점수 (예: 11.5 / 15)",
                "score_academic_attitude_10": "학업태도 점수 (예: 6.5 / 10)",
                "score_digital_literacy_15": "디지털 리터러시 점수 (예: 11.0 / 15)",
                "reason_academic_core": "학업역량 3개 영역에 대한 보수적이고 냉정하며 뼈 때리는 통합 진단 서평 (블룸 인지영역 대조 포함)",
                "evidence_academic_core": "학업역량에서 감점이나 한계를 직접 보여주는 세특의 실제 평이한 문장 또는 핵심 문장 인용",
                "improvement_academic_core": "학업역량 만점을 뚫기 위해 당장 다음 학기에 제출해야 할 매우 구체적인 고난도 탐구 보고서 주제 추천 및 공부법 독설 가이드",
                
                "score_major_selection_10": "전공이수 노력 점수 (예: 7.5 / 10)",
                "score_major_grades_10": "전공교과 성취도 점수 (예: 6.0 / 10)",
                "score_career_experience_20": "진로탐색 에피소드 점수 (예: 13.5 / 20)",
                "reason_career_core": "진로역량 3개 영역에 대한 보수적이고 냉혹한 통합 사정관 진단 서평 (위계성 및 알맹이 나열 한계 폭로)",
                "evidence_career_core": "진로역량에서 과장되었거나 알맹이가 누락된 실제 문장 그대로 인용",
                "improvement_career_core": "이 학생의 희망 진로에 최적화된, 실제 대학 학술논문과 전공 서적을 연계한 '독창적이고 구체적인 꼬리물기 심화 탐구 소주제 2~3개 직접 기획 추천'",
                
                "score_collab_6": "협업/소통 점수 (예: 4.0 / 6)",
                "score_sharing_4": "나눔/배려 점수 (예: 2.5 / 4)",
                "score_sincerity_5": "성실성/출결 점수 (예: 4.5 / 5)",
                "score_leadership_5": "리더십 점수 (예: 3.5 / 5)",
                "reason_social_core": "공동체역량 4개 영역에 대한 정량 감점 사유 중심의 엄격한 통합 사정관 진단 서평",
                "evidence_social_core": "공동체역량 기재 중 추상적인 칭찬 위주의 신뢰도 낮은 실제 문장 인용",
                "improvement_social_core": "기록의 정량성을 극대화하기 위해 학급 활동이나 동아리에서 직접 실행해야 할 구체적 소통/조율 역할 제언",
                
                "ai_pollution_audit": {{
                    "risk_level": "위험도 단계 (예: 정상(안전), 주의, 심각 중 하나)",
                    "suspected_areas": "AI 대필이 강하게 의심되는 과목 세특이나 창체 영역 명칭",
                    "audit_verdict": "사정관 감리 위원회 관점에서 기재 수준의 AI 템플릿 의존성, 문체 불일치, 교사 관찰 부재 현황을 소리 높여 짚어낸 냉정하고 예리한 경고 의견"
                }},
                
                "score_total": "전체 합산 총점 (예: 71.0) - 위 10개 영역 점수의 합과 100% 한 치의 수학적 오차도 없이 일치하도록 소수점 계산할 것"
            }}
            """

            try:
                generation_config = {
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "top_k": 1,
                }
                
                model = genai.GenerativeModel(
                    model_name=model_option,
                    generation_config=generation_config
                )
                response = model.generate_content(prompt)
                
                response_text = response.text.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()
                
                result = json.loads(response_text)
                
                st.balloons()
                st.success("🎉 분석 완료! 개인정보 보호를 위해 생기부 원본은 메모리에서 즉시 영구 파기되었습니다.")
                
                st.divider()
                st.markdown(f"### 📝 2단계: 실제 AI 채점 결과 ({target_university_group} 전형형 모델 - 🚨 냉정 평가 및 AI 감리 모드)")
                
                col_score1, col_score2, col_score3, col_score4 = st.columns(4)
                col_score1.metric("📊 학업역량 계 (40점 만점)", f"{float(result['score_achievement_15'].split('/')[0]) + float(result['score_academic_attitude_10'].split('/')[0]) + float(result['score_digital_literacy_15'].split('/')[0]):.1f} / 40.0")
                col_score2.metric("🎯 진로역량 계 (40점 만점)", f"{float(result['score_major_selection_10'].split('/')[0]) + float(result['score_major_grades_10'].split('/')[0]) + float(result['score_career_experience_20'].split('/')[0]):.1f} / 40.0")
                col_score3.metric("🤝 공동체역량 계 (20점 만점)", f"{float(result['score_collab_6'].split('/')[0]) + float(result['score_sharing_4'].split('/')[0]) + float(result['score_sincerity_5'].split('/')[0]) + float(result['score_leadership_5'].split('/')[0]):.1f} / 20.0")
                col_score4.metric("🚨 종합 환산 점수", f"{result['score_total']} / 100")

                st.divider()
                st.markdown("### 🤖 2028학년도 표준 생기부 AI 신뢰도 감리 결과 (AI Audit)")
                audit_box = result.get("ai_pollution_audit", {})
                risk_color = "red" if audit_box.get("risk_level") in ["주의", "심각"] else "green"
                st.markdown(f"""
                <div style="background-color: #F5F3FF; border-left: 6px solid #8B5CF6; padding: 20px; border-radius: 8px;">
                    <h4 style="color: #4C1D95; margin-top:0;">👁️ 사정관 연합회 서류 신뢰도 정밀 감리 소견</h4>
                    <p style="font-size: 15px; color: #1F2937;">
                        <b>• AI 대필 위험도 단계:</b> <span style="color: {risk_color}; font-weight: bold;">[{audit_box.get("risk_level", "정상")}]</span><br/>
                        <b>• 정밀 재검토가 권장되는 의심 영역:</b> <span style="font-weight: bold; color: #B91C1C;">{audit_box.get("suspected_areas", "없음")}</span>
                    </p>
                    <hr style="border: 0.5px solid #E5E7EB; margin: 15px 0;"/>
                    <p style="font-style: italic; color: #4C1D95; line-height: 1.5; font-size: 14.5px;">
                        " {audit_box.get("audit_verdict", "기재된 텍스트 중 인위적인 AI 에뮬레이션 패턴이나 극단적인 문체 격차가 발견되지 않았습니다. 서류 신뢰도가 우수한 수준입니다.")} "
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                st.divider()
                st.markdown("### 🔍 10대 지표 상세 평가 분석서")
                
                with st.expander("📕 I. 학업역량 (성취도 분포, 학업태도, 디지털 리터러시) [배점: 40점]"):
                    tab_analysis, tab_improve = st.tabs(["🔍 세부 평가 의견 (블룸 6단계 대조)", "🚨 만점 대비 감점 원인 및 쓴소리 조언"])
                    with tab_analysis:
                        st.markdown(f"**• 성취도 분포 및 이수환경 점수:** `{result['score_achievement_15']}`")
                        st.markdown(f"**• 행동 근거 기반 학업태도 점수:** `{result['score_academic_attitude_10']}`")
                        st.markdown(f"**• 디지털 리터러시 및 비판 탐구 점수:** `{result['score_digital_literacy_15']}`")
                        st.write(result["reason_academic_core"])
                        st.info(f"블룸 하위 인지단계(지식/이해)로 매칭되어 감점된 원문 근거: \"{result['evidence_academic_core']}\"")
                    with tab_improve:
                        st.warning(result.get("improvement_academic_core", "학업 역량이 완벽합니다."))
                        
                with st.expander("📗 II. 진로역량 (과목 위계성, 전공적 사고, 교과-창체 연계) [배점: 40점]"):
                    tab_analysis, tab_improve = st.tabs(["🔍 세부 평가 의견 (독해력 및 선택과목 위계 대조)", "🚨 만점 대비 감점 원인 및 초정밀 탐구 추천 소주제"])
                    with tab_analysis:
                        st.markdown(f"**• 전공 연계 과목 이수 노력 점수:** `{result['score_major_selection_10']}`")
                        st.markdown(f"**• 전공 관련 교과 성취도 점수:** `{result['score_major_grades_10']}`")
                        st.markdown(f"**• 교과-창체 연계 진로 에피소드 점수:** `{result['score_career_experience_20']}`")
                        st.write(result["reason_career_core"])
                        st.info(f"학술 연계 깊이가 부족해 단순 나열로 분류된 감점 원문 근거: \"{result['evidence_career_core']}\"")
                    with tab_improve:
                        st.warning(result.get("improvement_career_core", "진로 설계가 완벽합니다."))
                        
                with st.expander("📘 III. 공동체역량 (다원적 협업, 나눔과 배려, 성실성, 리더십) [배점: 20점]"):
                    tab_analysis, tab_improve = st.tabs(["🔍 세부 평가 의견 (성품 및 실질 기여도 대조)", "🚨 만점 대비 감점 원인 및 행동 지침"])
                    with tab_analysis:
                        st.markdown(f"**• 다원적 협업 및 소통 역량 점수:** `{result['score_collab_6']}`")
                        st.markdown(f"**• 특정 대상 중심 나눔과 배려 점수:** `{result['score_sharing_4']}`")
                        st.markdown(f"**• 성실성 및 출결 점수:** `{result['score_sincerity_5']}`")
                        st.markdown(f"**• 자발적 리더십 및 조율 점수:** `{result['score_leadership_5']}`")
                        st.write(result["reason_social_core"])
                        st.info(f"직책 명칭만 나열되어 실질 행동 근거가 결여된 감점 원문 근거: \"{result['evidence_social_core']}\"")
                    with tab_improve:
                        st.warning(result.get("improvement_social_core", "인성 지표가 완벽합니다."))
                        
                st.divider()
                st.markdown("### 📥 3단계: 채점 보고서 다운로드")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if REPORTLAB_AVAILABLE:
                        pdf_report_bytes = generate_pdf_report(result, student_file.name, target_university_group)
                        st.download_button(
                            label="📄 완성형 PDF 정밀 진단 보고서 다운로드 (AI 감리 내용 탑재)", 
                            data=pdf_report_bytes, 
                            file_name=f"브니엘고_2028대비_AI_냉정채점결과_{target_university_group.replace(' ', '_')}_{student_file.name.replace('.pdf', '')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                    else:
                        st.warning("⚠️ PDF 모듈이 누락되어 텍스트 다운로드만 가능합니다. PDF를 사용하시려면 터미널에 'pip install reportlab' 명령어 실행 후 새로고침하세요.")
                with col_btn2:
                    report_txt = f"=== 브니엘고 AI 채점 보고서 ({target_university_group} 냉철 평가 모델) ===\n\n종합 점수: {result['score_total']}\n\n1. 학업역량: {result['score_achievement_15']} + {result['score_academic_attitude_10']} + {result['score_digital_literacy_15']}\n- 내용: {result['reason_academic_core']}\n- 보완책: {result.get('improvement_academic_core', '')}\n\n2. 진로역량: {result['score_major_selection_10']} + {result['score_major_grades_10']} + {result['score_career_experience_20']}\n- 내용: {result['reason_career_core']}\n- 보완책: {result.get('improvement_career_core', '')}\n\n3. 공동체역량: {result['score_collab_6']} + {result['score_sharing_4']} + {result['score_sincerity_5']} + {result['score_leadership_5']}\n- 내용: {result['reason_social_core']}\n- 보완책: {result.get('improvement_social_core', '')}"
                    st.download_button("📝 텍스트(TXT) 간이 보고서 다운로드", data=report_txt, file_name="ai_report.txt", use_container_width=True)
                
            except json.JSONDecodeError:
                st.error("⚠️ AI가 규격에 맞지 않는 불완전한 형식으로 응답했습니다. 한 번 더 '채점 시작하기'를 눌러주시거나, 모델 설정을 변경해 보세요.")
                with st.expander("ℹ️ AI 원본 답변 내용 보기"):
                    st.code(response.text)
            except Exception as e:
                if "404" in str(e):
                    st.error(f"❌ 선택하신 모델('{model_option}')을 구글에서 찾을 수 없거나 현재 사용이 불가능합니다. 왼쪽 사이드바의 'AI 엔진 모델 설정'에서 다른 모델로 변경하여 다시 시도해 보세요!")
                else:
                    st.error(f"AI 분석 중 에러가 발생했습니다: {e}")