# PDF OCR 변환기

이 프로젝트는 PDF 파일을 OCR 처리하여 마크다운 형식으로 변환하는 웹 애플리케이션입니다. Mistral AI의 OCR 기능을 사용하여 텍스트를 추출하고, 선택적으로 OpenAI를 사용하여 맞춤법을 교정할 수 있습니다.

## 주요 기능

- PDF 파일 업로드 및 OCR 처리
- 추출된 텍스트를 마크다운 형식으로 변환
- 이미지 추출 및 저장
- 선택적 맞춤법 교정 (OpenAI 사용)
- 실시간 처리 상태 표시
- 결과 미리보기 및 ZIP 파일 다운로드


1. 필요한 패키지를 설치합니다:
```bash
pip install -r requirements.txt
```

2. 환경 변수 설정:
`.env` 파일을 생성하고 다음 내용을 추가합니다:
```
MISTRAL_API_KEY=your_mistral_api_key
OPENAI_API_KEY=your_openai_api_key  # 선택사항
```

## 사용 방법

1. 애플리케이션을 실행합니다:
```bash
python app.py
```

2. 웹 브라우저에서 `http://localhost:5001`에 접속합니다.

3. Mistral API 키를 입력합니다 (또는 .env 파일에 설정).

4. PDF 파일을 선택하고 "PDF 변환" 버튼을 클릭합니다.

5. 처리된 결과를 다운로드하거나 미리볼 수 있습니다.

## 기술 스택

- **백엔드**: Python, Flask
- **OCR 처리**: Mistral AI
- **맞춤법 교정**: OpenAI GPT-4 (선택사항)
- **프론트엔드**: HTML, CSS, JavaScript
- **마크다운 렌더링**: marked.js
- **수식 렌더링**: MathJax

## 주의사항

- Mistral API 키가 필요합니다.
- 맞춤법 교정을 사용하려면 OpenAI API 키가 필요합니다.
- 대용량 PDF 파일의 경우 처리 시간이 길어질 수 있습니다.


