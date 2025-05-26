import os
import json
import base64
import shutil
import zipfile
import re # 정규식 모듈 가져오기
from pathlib import Path
from uuid import uuid4
from flask import Flask, request, render_template, jsonify, send_from_directory, url_for
from mistralai import Mistral, DocumentURLChunk
from mistralai.models import OCRResponse
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

print("--- .env 로딩 디버그 ---")
dotenv_api_key = os.getenv("MISTRAL_API_KEY")
if dotenv_api_key:
    print(f"API 키가 .env에서 로드됨 (첫 4자): {dotenv_api_key[:4]}...")
else:
    print("API 키가 .env에서 로드되지 않음. .env 파일과 설정을 확인하세요.")
print("--- 디버그 종료 ---")


app = Flask(__name__)

# --- 설정 ---
UPLOAD_FOLDER = Path(os.getenv('UPLOAD_FOLDER', 'uploads'))
OUTPUT_FOLDER = Path(os.getenv('OUTPUT_FOLDER', 'output'))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {'pdf'}

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

# --- 헬퍼 함수 ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def replace_images_in_markdown_with_wikilinks(markdown_str: str, image_mapping: dict) -> str:
    updated_markdown = markdown_str
    for original_id, new_name in image_mapping.items():
        updated_markdown = updated_markdown.replace(
            f"![{original_id}]({original_id})",
            f"![[{new_name}]]"
        )
    return updated_markdown

# --- 핵심 처리 로직 ---

def process_pdf(pdf_path: Path, api_key: str, openai_api_key: str, session_output_dir: Path) -> tuple[str, str, list[str], Path, Path]:
    """
    Mistral OCR을 사용하여 단일 PDF 파일을 처리하고 결과를 저장합니다.
    OpenAI API를 사용하여 맞춤법을 교정합니다 (OpenAI API 키가 제공된 경우).

    반환값:
        튜플 (pdf_base_name, final_markdown_content, list_of_image_filenames, path_to_markdown_file, path_to_images_dir)
    예외:
        Exception: 처리 오류 발생 시.
    """
    pdf_base = pdf_path.stem
    pdf_base_sanitized = secure_filename(pdf_path.stem) # 디렉토리/파일 이름에 안전한 버전 사용
    print(f"{pdf_path.name} 처리 중...")

    pdf_output_dir = session_output_dir / pdf_base_sanitized
    pdf_output_dir.mkdir(exist_ok=True)
    images_dir = pdf_output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    client = Mistral(api_key=api_key)
    ocr_response: OCRResponse | None = None
    uploaded_file = None # uploaded_file 초기화

    try:
        print(f"  {pdf_path.name}을(를) Mistral에 업로드 중...")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        uploaded_file = client.files.upload(
            file={"file_name": pdf_path.name, "content": pdf_bytes}, purpose="ocr"
        )

        print(f"  파일 업로드 완료 (ID: {uploaded_file.id}). 서명된 URL 가져오는 중...")
        signed_url = client.files.get_signed_url(file_id=uploaded_file.id, expiry=60)

        print(f"  OCR API 호출 중...")
        ocr_response = client.ocr.process(
            document=DocumentURLChunk(document_url=signed_url.url),
            model="mistral-ocr-latest",
            include_image_base64=True
        )
        print(f"  {pdf_path.name}에 대한 OCR 처리 완료.")

        # 선택 사항: Raw OCR 응답 저장
        ocr_json_path = pdf_output_dir / "ocr_response.json"
        try:
            with open(ocr_json_path, "w", encoding="utf-8") as json_file:
                if hasattr(ocr_response, 'model_dump'):
                    json.dump(ocr_response.model_dump(), json_file, indent=4, ensure_ascii=False)
                else:
                     json.dump(ocr_response.dict(), json_file, indent=4, ensure_ascii=False)
            print(f"  Raw OCR 응답이 {ocr_json_path}에 저장됨")
        except Exception as json_err:
            print(f"  경고: Raw OCR JSON을 저장할 수 없음: {json_err}")

        # OCR 응답 처리 -> 마크다운 및 이미지
        global_image_counter = 1
        updated_markdown_pages = []
        extracted_image_filenames = [] # 미리보기용 파일명 저장

        print(f"  이미지 추출 및 마크다운 생성 중...")
        for page_index, page in enumerate(ocr_response.pages):
            current_page_markdown = page.markdown
            page_image_mapping = {}

            for image_obj in page.images:
                base64_str = image_obj.image_base64
                if not base64_str: continue # 이미지 데이터가 없으면 건너뛰기

                if base64_str.startswith("data:"):
                     try: base64_str = base64_str.split(",", 1)[1]
                     except IndexError: continue

                try: image_bytes = base64.b64decode(base64_str)
                except Exception as decode_err:
                    print(f"  경고: 페이지 {page_index+1}의 이미지 {image_obj.id}에 대한 Base64 디코딩 오류: {decode_err}")
                    continue

                original_ext = Path(image_obj.id).suffix
                ext = original_ext if original_ext else ".png"
                new_image_name = f"{pdf_base_sanitized}_p{page_index+1}_img{global_image_counter}{ext}"
                global_image_counter += 1

                image_output_path = images_dir / new_image_name
                try:
                    with open(image_output_path, "wb") as img_file:
                        img_file.write(image_bytes)
                    extracted_image_filenames.append(new_image_name) # 미리보기 목록에 추가
                    page_image_mapping[image_obj.id] = new_image_name
                except IOError as io_err:
                     print(f"  경고: 이미지 파일 {image_output_path}을(를) 쓸 수 없음: {io_err}")
                     continue

            updated_page_markdown = replace_images_in_markdown_with_wikilinks(current_page_markdown, page_image_mapping)
            updated_markdown_pages.append(updated_page_markdown)

        final_markdown_content = "\n\n---\n\n".join(updated_markdown_pages) # 페이지 구분자
        # 맞춤법 교정 단계 추가
        if openai_api_key:
            print(f"  OpenAI를 사용하여 맞춤법 교정 중...")
            try:
                corrected_content = correct_spelling(final_markdown_content, openai_api_key)
                if corrected_content:  # 교정된 내용이 있으면 사용
                    final_markdown_content = corrected_content
                    print(f"  맞춤법 교정 완료")
                else:
                    print(f"  맞춤법 교정 실패, 원본 텍스트 사용")
            except Exception as spell_err:
                print(f"  맞춤법 교정 중 오류 발생: {spell_err}")
                # 오류 발생 시 원본 텍스트 유지
        else:
            print(f"  OpenAI 맞춤법 교정 건너뜀 (사용자 설정 또는 API 키 없음)")
        output_markdown_path = pdf_output_dir / f"{pdf_base_sanitized}_output.md"

        try:
            with open(output_markdown_path, "w", encoding="utf-8") as md_file:
                md_file.write(final_markdown_content)
            print(f"  마크다운이 {output_markdown_path}에 성공적으로 생성됨")
        except IOError as io_err:
            raise Exception(f"최종 마크다운 파일 쓰기 실패: {io_err}") from io_err

        # Mistral 파일 정리
        try:
            client.files.delete(file_id=uploaded_file.id)
            print(f"  Mistral에서 임시 파일 {uploaded_file.id} 삭제됨.")
        except Exception as delete_err: # 일반 Exception 캐치
            print(f"  경고: Mistral에서 파일 {uploaded_file.id}을(를) 삭제할 수 없음: {delete_err}")

        # 실제 콘텐츷와 이미지 목록 반환
        return pdf_base_sanitized, final_markdown_content, extracted_image_filenames, output_markdown_path, images_dir

    except Exception as e:
        error_str = str(e)
        # 예외 문자열에서 JSON 오류 메시지 추출 시도
        json_index = error_str.find('{')
        if json_index != -1:
            try:
                error_json = json.loads(error_str[json_index:])
                error_msg = error_json.get("message", error_str)
            except Exception:
                error_msg = error_str
        else:
            error_msg = error_str
        print(f"  {pdf_path.name} 처리 오류: {error_msg}")
        # 오류 발생 시에도 정리 시도
        if uploaded_file:
            try: client.files.delete(file_id=uploaded_file.id)
            except Exception: pass
        raise Exception(error_msg)


def create_zip_archive(output_dir, zip_path):
    """출력 디렉토리의 내용을 ZIP 파일로 압축합니다."""
    print(f"ZIP 파일 생성 중: {zip_path}")
    print(f"출력 디렉토리: {output_dir}")
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(output_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, output_dir)
                    print(f"ZIP에 추가 중: {file_path} -> {arcname}")
                    zipf.write(file_path, arcname)
        print(f"ZIP 파일 생성 완료: {zip_path}")
        return True
    except Exception as e:
        print(f"ZIP 파일 생성 중 오류 발생: {str(e)}")
        return False

def correct_spelling(text: str, api_key: str) -> str:
    """
    OpenAI API를 사용하여 텍스트의 맞춤법을 교정합니다.
    """
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o", # 또는 "gpt-3.5-turbo"
            messages=[
                {"role": "system", "content": """당신은 한국어 맞춤법과 문법을 교정하는 전문가입니다. 다음 지침을 엄격히 따르세요:

1. OCR 오류 교정:
   - 잘못 인식된 단어를 올바른 단어로 교정 (예: '매재대학교' → '배재대학교')
   - 일반적인 OCR 오류 패턴을 인식하고 수정 (예: 'ㅂ'과 'ㅁ' 혼동, 'ㄱ'과 'ㄴ' 혼동 등)

2. 문맥 기반 교정:
   - 문맥을 고려하여 단어의 올바른 형태를 결정
   - 특히 대학교, 기관명, 인명 등은 정확한 표기 확인

3. 형식 유지:
   - 마크다운 문법과 서식은 그대로 유지
   - 이미지 링크(![[...]])는 절대 수정하지 않음
   - 들여쓰기, 줄바꿈, 특수문자는 원본 그대로 유지

4. 문제 텍스트 구분:
   - 아래와 같은 유형의 문제는 절대 풀이하지 말고, 원문 그대로 유지하세요.
     * 객관식, 주관식, 단답형 문제
     * 문장 끝에 '?'가 있거나 '다음 중', '무엇인가?' 등의 표현 포함
     * 문제 번호가 있는 경우 (예: 1. 2. 3.)

5. 교정 범위:
   - 맞춤법 오류
   - 띄어쓰기
   - 문장 부호
   - OCR로 인한 잘못된 단어 인식

6. 주의사항:
   - 확실하지 않은 경우 원본 유지
   - 전문 용어나 고유명사는 신중하게 검토
   - 수식이나 코드 블록은 수정하지 않음
   - 절대 문제를 풀이하거나 해설하지 마세요.
"""},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"맞춤법 교정 중 오류 발생: {e}")
        return text  # 오류 발생 시 원본 텍스트 반환


# --- Flask 라우트 ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def handle_process():
    if 'pdf_files' not in request.files:
        return jsonify({"error": "요청에 PDF 파일 부분이 없습니다"}), 400

    files = request.files.getlist('pdf_files')
    api_key = request.form.get('api_key')
    # OpenAI API 키 가져오기
    openai_api_key = request.form.get('openai_api_key')
    # OpenAI 사용 여부 체크박스 값 가져오기
    use_openai = request.form.get('use_openai') == 'true'
    
    # OpenAI API 키가 비어 있으면 환경 변수에서 가져오기 시도
    if not openai_api_key and use_openai:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            print(f"환경에서 OpenAI API 키 사용 중 (첫 4자): {openai_api_key[:4]}...")
    
    # OpenAI 사용 여부가 false이면 API 키를 None으로 설정
    if not use_openai:
        openai_api_key = None
        print("사용자 설정에 따라 OpenAI 맞춤법 교정을 사용하지 않습니다.")
    
    if not api_key:
        print("웹 폼에서 API 키가 비어 있습니다.")
        # 폴백 API 키가 .env(또는 다른 서버 측 구성)에 있는지 확인
        api_key_fallback = os.getenv("MISTRAL_API_KEY") # 환경에서 다시 가져오기 시도
        if api_key_fallback:
            api_key = api_key_fallback
            print(f"환경에서 폴백 API 키 사용 중 (첫 4자): {api_key[:4]}...") # 디버그 출력
        else:
            return jsonify({"error": "Mistral API 키가 필요합니다"}), 400
    else:
        print(f"웹 폼에서 API 키 (첫 4자): {api_key[:4]}...") # 디버그 출력

    if not files or all(f.filename == '' for f in files):
         return jsonify({"error": "선택된 PDF 파일이 없습니다"}), 400

    valid_files, invalid_files = [], []
    for f in files:
        if f and allowed_file(f.filename): valid_files.append(f)
        elif f and f.filename != '': invalid_files.append(f.filename)

    if not valid_files:
         # ... (이전과 같은 오류 처리) ...
         error_msg = "유효한 PDF 파일을 찾을 수 없습니다."
         if invalid_files: error_msg += f" 건너뛴 유효하지 않은 파일: {', '.join(invalid_files)}"
         return jsonify({"error": error_msg}), 400


    session_id = str(uuid4())
    session_upload_dir = UPLOAD_FOLDER / session_id
    session_output_dir = OUTPUT_FOLDER / session_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)
    session_output_dir.mkdir(parents=True, exist_ok=True)

    processed_files_results = [] # 명확성을 위해 이름 변경
    processing_errors = []
    if invalid_files: processing_errors.append(f"PDF가 아닌 파일 건너뜀: {', '.join(invalid_files)}")

    for file in valid_files:
        original_filename = file.filename
        filename_sanitized = secure_filename(original_filename)
        pdf_base_sanitized = secure_filename(Path(original_filename).stem)
        if not pdf_base_sanitized:
            pdf_base_sanitized = "file"
        temp_pdf_path = session_upload_dir / filename_sanitized
        zip_filename = f"{pdf_base_sanitized}_output.zip"
        zip_output_path = session_output_dir / zip_filename
        individual_output_dir = session_output_dir / pdf_base_sanitized

        try:
            print(f"업로드된 파일을 임시로 저장 중: {temp_pdf_path}")
            file.save(temp_pdf_path)

            # PDF 처리 - 새 반환 값 캡처
            processed_pdf_base, markdown_content, image_filenames, md_path, img_dir = process_pdf(
                temp_pdf_path, api_key, openai_api_key, session_output_dir
            )

            # ZIP 생성 (개별 출력 디렉토리 사용)
            create_zip_archive(individual_output_dir, zip_output_path)

            download_url = url_for('download_file', session_id=session_id, filename=zip_filename, _external=True)

            # 미리보기 데이터를 포함한 결과 저장
            processed_files_results.append({
                "original_filename": original_filename, # 표시용 원본 이름 유지
                "zip_filename": zip_filename,
                "download_url": download_url,
                "preview": {
                    "markdown": markdown_content,
                    "images": image_filenames,
                    "pdf_base": processed_pdf_base # process_pdf에서 반환된 안전한 기본 이름 사용
                }
            })
            print(f"성공적으로 처리 및 압축됨: {original_filename}")

        except Exception as e:
            print(f"오류: {original_filename} 처리 실패: {e}")
            processing_errors.append(f"{original_filename}: 처리 오류 - {e}")
        finally:
            if temp_pdf_path.exists():
                try: temp_pdf_path.unlink()
                except OSError as unlink_err: print(f"경고: 임시 파일 {temp_pdf_path}을(를) 삭제할 수 없음: {unlink_err}")

    # 세션 업로드 디렉토리 정리
    try:
        shutil.rmtree(session_upload_dir)
        print(f"세션 업로드 디렉토리 정리됨: {session_upload_dir}")
    except OSError as rmtree_err:
        print(f"경고: 세션 업로드 디렉토리 {session_upload_dir}을(를) 삭제할 수 없음: {rmtree_err}")

    if not processed_files_results and processing_errors:
         return jsonify({"error": "모든 PDF 처리 시도가 실패했습니다.", "details": processing_errors}), 500
    elif not processed_files_results:
         return jsonify({"error": "성공적으로 처리된 파일이 없습니다."}), 500
    else:
        # 이미지 URL 구성을 위해 session_id와 함께 결과 반환
        return jsonify({
            "success": True,
            "session_id": session_id, # 여기에 session_id 추가됨
            "results": processed_files_results, # 'downloads'에서 이름 변경됨
            "errors": processing_errors
        }), 200

# --- 이미지 제공을 위한 새 라우트 ---
@app.route('/view_image/<session_id>/<pdf_base>/<filename>')
def view_image(session_id, pdf_base, filename):
    """인라인 표시를 위해 추출된 이미지 파일을 제공합니다."""
    safe_session_id = secure_filename(session_id)
    safe_pdf_base = secure_filename(pdf_base)
    safe_filename = secure_filename(filename)

    # *pdf_base* 특정 출력 폴더에 상대적인 경로 구성
    directory = OUTPUT_FOLDER / safe_session_id / safe_pdf_base / "images"
    file_path = directory / safe_filename

    # 보안 검사
    if not str(file_path.resolve()).startswith(str(directory.resolve())):
         return "유효하지 않은 경로", 400
    if not file_path.is_file():
         return "이미지를 찾을 수 없음", 404

    print(f"이미지 제공 중: {file_path}")
    # 인라인 표시를 위해 as_attachment=True *없이* 전송
    return send_from_directory(directory, safe_filename)


@app.route('/download/<session_id>/<filename>')
def download_file(session_id, filename):
    """다운로드를 위해 생성된 ZIP 파일을 제공합니다."""
    safe_session_id = secure_filename(session_id)
    safe_filename = secure_filename(filename)
    directory = OUTPUT_FOLDER / safe_session_id
    file_path = directory / safe_filename

    # 파일 존재 여부 확인 및 로깅
    print(f"다운로드 요청: {file_path}")
    print(f"파일 존재 여부: {file_path.exists()}")
    print(f"디렉토리 존재 여부: {directory.exists()}")

    if not str(file_path.resolve()).startswith(str(OUTPUT_FOLDER.resolve())):
        print("보안 검사 실패: 유효하지 않은 경로")
        return "유효하지 않은 경로", 400
        
    if not file_path.is_file():
        print(f"파일을 찾을 수 없음: {file_path}")
        return "파일을 찾을 수 없음", 404

    try:
        print(f"다운로드용 ZIP 제공 중: {file_path}")
        return send_from_directory(str(directory), safe_filename, as_attachment=True)
    except Exception as e:
        print(f"다운로드 중 오류 발생: {str(e)}")
        return f"다운로드 중 오류 발생: {str(e)}", 500

if __name__ == '__main__':
     host = os.getenv('FLASK_HOST', '127.0.0.1')
     port = int(os.getenv('FLASK_PORT', 5001))
     debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
     app.run(host=host, port=port, debug=debug_mode)