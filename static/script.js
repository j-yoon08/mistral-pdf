document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('ocr-form');
    const fileInput = document.getElementById('pdf-files');
    const useOpenaiCheckbox = document.getElementById('use_openai'); // 추가: OpenAI 사용 여부 체크박스
    const submitBtn = document.getElementById('submit-btn');
    const statusLog = document.getElementById('status-log');
    const loader = document.getElementById('loader');

    // Result Areas
    const resultsArea = document.getElementById('results-area');
    const downloadLinksList = document.getElementById('download-links');
    const previewArea = document.getElementById('preview-area'); // New preview area
    const previewContent = document.getElementById('preview-content'); // Container for previews

    // Error Area
    const errorArea = document.getElementById('error-area');
    const errorMessage = document.getElementById('error-message');

    function logStatus(message) {
        console.log(message);
        statusLog.textContent += message + '\n';
        statusLog.scrollTop = statusLog.scrollHeight;
    }

    function resetUI() {
        statusLog.textContent = '준비 완료. 파일을 선택하고 "PDF 변환"을 클릭하세요.';
        resultsArea.style.display = 'none';
        downloadLinksList.innerHTML = '';
        previewArea.style.display = 'none';   // Hide preview area
        previewContent.innerHTML = '';        // Clear preview content
        errorArea.style.display = 'none';
        errorMessage.textContent = '';
        submitBtn.disabled = false;
        loader.style.display = 'none';
    }

    // --- Function to render preview ---
    function renderPreview(resultItem, sessionId) {
        if (!resultItem.preview) return;

        const previewContainer = document.createElement('div');
        previewContainer.classList.add('preview-item');
        previewContainer.classList.add('collapsed'); // Initially collapse

        // --- Create the TOGGLE element ---
        const toggleButton = document.createElement('div');
        toggleButton.classList.add('preview-toggle');
        toggleButton.innerHTML = `<span>📄 ${resultItem.original_filename} 미리보기</span>`;
        previewContainer.appendChild(toggleButton);

        // --- Create the INNER CONTENT div (that will be shown/hidden) ---
        const contentInner = document.createElement('div');
        contentInner.classList.add('preview-content-inner');

        // --- Markdown Preview ---
        const markdownSection = document.createElement('div');
        markdownSection.classList.add('markdown-preview');

        let markdownForDisplay = resultItem.preview.markdown;

        markdownForDisplay = markdownForDisplay.replace(
            /!\[\[(.*?)\]\]/g,
            (match, filename) => {
                const imageUrl = `/view_image/${sessionId}/${resultItem.preview.pdf_base}/${filename.trim()}`;
                const safeAltText = filename.trim().replace(/"/g, '"');
                return `<img src="${imageUrl}" alt="${safeAltText}" style="max-width: 90%; height: auto; display: block; margin: 10px 0; border: 1px solid #ccc;">`;
            }
        );

        if (typeof marked !== 'undefined') {
            const renderedMarkdownDiv = document.createElement('div');
            renderedMarkdownDiv.innerHTML = marked.parse(markdownForDisplay);
            markdownSection.appendChild(renderedMarkdownDiv);
        } else {
            logStatus("Warning: Marked.js library not found. Falling back to raw Markdown preview.");
            const markdownPre = document.createElement('pre');
            markdownPre.textContent = markdownForDisplay;
            markdownSection.appendChild(markdownPre);
        }

        contentInner.appendChild(markdownSection);

        // --- Image Preview (Optional: List images separately) ---
        if (resultItem.preview.images && resultItem.preview.images.length > 0) {
            const imageSection = document.createElement('div');
            imageSection.classList.add('image-preview');

            resultItem.preview.images.forEach(imageFilename => {
                const img = document.createElement('img');
                img.src = `/view_image/${sessionId}/${resultItem.preview.pdf_base}/${imageFilename}`;
                const safeAltText = imageFilename.replace(/"/g, '"');
                img.alt = safeAltText;
                img.style.maxWidth = '150px';
                img.style.height = 'auto';
                img.style.margin = '5px';
                img.style.border = '1px solid #ddd';
                img.style.display = 'inline-block';
                img.onerror = () => {
                    img.alt = `Could not load: ${imageFilename}`;
                    img.style.border = '1px solid red';
                 };
                imageSection.appendChild(img);
            });
            contentInner.appendChild(imageSection);
        }

        // --- Append the inner content to the preview container ---
        previewContainer.appendChild(contentInner);

        // --- Add EVENT LISTENER to toggle button ---
        toggleButton.addEventListener('click', () => {
            previewContainer.classList.toggle('collapsed'); // Toggle collapsed class
        });

        previewContent.appendChild(previewContainer);
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        resetUI();
    
        // settings 모달에서 저장된 API 키 사용
        const apiKey = localStorage.getItem('mistral_api_key') || '';
        const openaiApiKey = localStorage.getItem('openai_api_key') || '';
        const files = fileInput.files;
    
        if (files.length === 0) {
             logStatus('오류: 최소 하나의 PDF 파일이 필요합니다.');
             errorMessage.textContent = '최소 하나의 PDF 파일이 필요합니다.';
             errorArea.style.display = 'block';
             return;
        }
    
        submitBtn.disabled = true;
        loader.style.display = 'block';
        logStatus('PDF 처리 시작...');

        const formData = new FormData();
        formData.append('api_key', apiKey);
        formData.append('openai_api_key', openaiApiKey);
        formData.append('use_openai', useOpenaiCheckbox.checked ? 'true' : 'false');

        for (let i = 0; i < files.length; i++) {
            formData.append('pdf_files', files[i]);
            logStatus(`파일 추가 중: ${files[i].name}`);
        }

        try {
            logStatus('파일 업로드 및 서버 요청 중...');
            const response = await fetch('/process', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                let errorData = { error: `서버 오류: ${response.status} ${response.statusText}` };
                try { errorData = await response.json(); } catch (e) { /* Ignore if response not JSON */ }
                throw new Error(errorData.error || `서버 오류: ${response.status}`);
            }

            const result = await response.json();

            if (result.success && result.results && result.session_id) {
                logStatus('처리 완료!');
                const sessionId = result.session_id;

                if (result.results.length > 0) {
                    resultsArea.style.display = 'block';
                    result.results.forEach(item => {
                        const li = document.createElement('li');
                        
                        // 새로운 카드 스타일 구조
                        const downloadInfo = document.createElement('div');
                        downloadInfo.className = 'download-info';
                        
                        const downloadTitle = document.createElement('div');
                        downloadTitle.className = 'download-title';
                        downloadTitle.innerHTML = `<i class="fas fa-file-archive"></i> ${item.original_filename}`;
                        
                        const downloadSubtitle = document.createElement('div');
                        downloadSubtitle.className = 'download-subtitle';
                        downloadSubtitle.textContent = `ZIP 파일 • ${item.zip_filename}`;
                        
                        downloadInfo.appendChild(downloadTitle);
                        downloadInfo.appendChild(downloadSubtitle);
                        
                        const downloadBtn = document.createElement('a');
                        downloadBtn.href = item.download_url;
                        downloadBtn.className = 'download-btn';
                        downloadBtn.innerHTML = '<i class="fas fa-download"></i> 다운로드';
                        
                        li.appendChild(downloadInfo);
                        li.appendChild(downloadBtn);
                        downloadLinksList.appendChild(li);

                        renderPreview(item, sessionId);
                    });

                    if (previewContent.hasChildNodes()) {
                       previewArea.style.display = 'block';
                    }

                } else {
                     logStatus("처리가 완료되었지만 다운로드하거나 미리볼 수 있는 결과가 없습니다.");
                }

                if (result.errors && result.errors.length > 0) {
                    logStatus('\n--- 경고/부분 오류 ---');
                    result.errors.forEach(err => logStatus(`- ${err}`));
                    logStatus('-------------------------------\n');
                }

            } else if (result.error) {
                 throw new Error(result.error);
            } else {
                 throw new Error('서버로부터 예상치 못한 응답을 받았습니다.');
            }

        } catch (error) {
            logStatus(`오류 발생: ${error.message}`);
            console.error('처리 오류:', error);
            errorMessage.textContent = error.message;
            errorArea.style.display = 'block';
        } finally {
            submitBtn.disabled = false;
            loader.style.display = 'none';
            logStatus('다음 작업을 위해 준비되었습니다.');
        }
    });

    // 체크박스 상태 변경 시 이벤트 리스너
    useOpenaiCheckbox.addEventListener('change', () => {
        // OpenAI 체크박스 상태에 따라 API 키 입력 필드 활성화/비활성화
        // This function is now empty as the logic is handled in the form submission
    });
});