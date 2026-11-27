// ===== Main JavaScript =====

// DOM Ready
document.addEventListener('DOMContentLoaded', function() {
    initFlashMessages();
    initLikeButtons();
    initReportModal();
    initFileUpload();
    initCommentForms();
    initAnswerForm();
});

// Flash Messages Auto-dismiss
function initFlashMessages() {
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach(flash => {
        setTimeout(() => {
            flash.style.opacity = '0';
            flash.style.transform = 'translateY(-10px)';
            setTimeout(() => flash.remove(), 300);
        }, 4000);
    });
}

// Like Button Handling
function initLikeButtons() {
    document.querySelectorAll('.post-action-btn[data-post-id]').forEach(btn => {
        btn.addEventListener('click', handleLike);
    });
}

async function handleLike(e) {
    const btn = e.currentTarget;
    const postId = btn.dataset.postId;
    const isLiked = btn.classList.contains('liked');
    
    if (btn.disabled) return;
    btn.disabled = true;
    
    try {
        const response = await fetch(`/post/${postId}/like`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            const countEl = btn.querySelector('.like-count');
            if (countEl) countEl.textContent = data.like_count;
            
            if (data.liked) {
                btn.classList.add('liked');
                btn.querySelector('.like-icon').textContent = '❤️';
            } else {
                btn.classList.remove('liked');
                btn.querySelector('.like-icon').textContent = '🤍';
            }
        } else {
            showToast(data.error || 'エラーが発生しました');
        }
    } catch (err) {
        showToast('通信エラーが発生しました');
    } finally {
        btn.disabled = false;
    }
}

// Report Modal
let currentReportPostId = null;

function initReportModal() {
    const modal = document.getElementById('reportModal');
    if (!modal) return;
    
    const openBtns = document.querySelectorAll('[data-report-post-id]');
    const closeBtn = modal.querySelector('.modal-close');
    const cancelBtn = modal.querySelector('.modal-cancel');
    const form = modal.querySelector('#reportForm');
    
    openBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            currentReportPostId = btn.dataset.reportPostId;
            modal.classList.add('show');
            document.body.style.overflow = 'hidden';
        });
    });
    
    function closeModal() {
        modal.classList.remove('show');
        document.body.style.overflow = '';
        form.reset();
        currentReportPostId = null;
    }
    
    closeBtn?.addEventListener('click', closeModal);
    cancelBtn?.addEventListener('click', closeModal);
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
    
    form?.addEventListener('submit', handleReport);
    
    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('show')) {
            closeModal();
        }
    });
}

async function handleReport(e) {
    e.preventDefault();
    
    if (!currentReportPostId) return;
    
    const form = e.target;
    const submitBtn = form.querySelector('button[type="submit"]');
    const reasonInput = form.querySelector('input[name="reason"]:checked');
    const detailInput = form.querySelector('textarea[name="detail"]');
    
    if (!reasonInput) {
        showToast('通報理由を選択してください');
        return;
    }
    
    submitBtn.disabled = true;
    submitBtn.textContent = '送信中...';
    
    try {
        const formData = new FormData();
        formData.append('reason', reasonInput.value);
        formData.append('detail', detailInput.value);
        
        const response = await fetch(`/post/${currentReportPostId}/report`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('通報しました。ご協力ありがとうございます。');
            document.getElementById('reportModal').classList.remove('show');
            document.body.style.overflow = '';
            form.reset();
        } else {
            showToast(data.error || '通報に失敗しました');
        }
    } catch (err) {
        showToast('通信エラーが発生しました');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '送信する';
    }
}

// File Upload Preview
function initFileUpload() {
    const fileInput = document.getElementById('imageUpload');
    if (!fileInput) return;
    
    const label = fileInput.closest('.file-upload-label');
    const previewContainer = document.getElementById('imagePreview');
    
    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        
        if (file) {
            // Validate
            const validTypes = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
            if (!validTypes.includes(file.type)) {
                showToast('対応していないファイル形式です (PNG, JPG, GIF, WebPのみ)');
                fileInput.value = '';
                return;
            }
            
            if (file.size > 5 * 1024 * 1024) {
                showToast('ファイルサイズは5MB以下にしてください');
                fileInput.value = '';
                return;
            }
            
            // Show preview
            label.classList.add('has-file');
            label.querySelector('.file-upload-icon').textContent = '✅';
            
            if (previewContainer) {
                const reader = new FileReader();
                reader.onload = (event) => {
                    previewContainer.innerHTML = `<img src="${event.target.result}" class="file-upload-preview" alt="プレビュー">`;
                };
                reader.readAsDataURL(file);
            }
        } else {
            label.classList.remove('has-file');
            label.querySelector('.file-upload-icon').textContent = '📷';
            if (previewContainer) previewContainer.innerHTML = '';
        }
    });
}

// Comment Forms
function initCommentForms() {
    document.querySelectorAll('.comment-form form').forEach(form => {
        form.addEventListener('submit', handleCommentSubmit);
    });
}

async function handleCommentSubmit(e) {
    e.preventDefault();
    
    const form = e.target;
    const postId = form.dataset.postId;
    const contentInput = form.querySelector('textarea[name="content"]');
    const nicknameInput = form.querySelector('input[name="nickname"]');
    const submitBtn = form.querySelector('button[type="submit"]');
    const commentsList = document.getElementById('commentsList');
    
    const content = contentInput.value.trim();
    const nickname = nicknameInput.value.trim() || '匿名';
    
    if (!content) {
        showToast('コメントを入力してください');
        return;
    }
    
    submitBtn.disabled = true;
    submitBtn.textContent = '投稿中...';
    
    try {
        const formData = new FormData();
        formData.append('content', content);
        formData.append('nickname', nickname);
        
        const response = await fetch(`/post/${postId}/comment`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            contentInput.value = '';
            // Reload comments
            if (commentsList) {
                const newComment = document.createElement('div');
                newComment.className = 'comment-card';
                newComment.innerHTML = `
                    <div class="comment-header">
                        <span class="comment-nickname">${escapeHtml(nickname)}</span>
                        <span class="comment-time">たった今</span>
                    </div>
                    <div class="comment-content">${escapeHtml(content)}</div>
                `;
                commentsList.insertBefore(newComment, commentsList.firstChild);
            }
            showToast('コメントしました');
        } else {
            showToast(data.error || 'コメントに失敗しました');
        }
    } catch (err) {
        showToast('通信エラーが発生しました');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '送信';
    }
}

// Answer Form (Question Page)
function initAnswerForm() {
    const form = document.getElementById('answerForm');
    if (!form) return;
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const contentInput = form.querySelector('textarea[name="content"]');
        const nicknameInput = form.querySelector('input[name="nickname"]');
        const submitBtn = form.querySelector('button[type="submit"]');
        
        const content = contentInput.value.trim();
        const nickname = nicknameInput.value.trim() || '匿名';
        
        if (!content) {
            showToast('回答を入力してください');
            return;
        }
        
        submitBtn.disabled = true;
        submitBtn.textContent = '投稿中...';
        
        try {
            const formData = new FormData();
            formData.append('content', content);
            formData.append('nickname', nickname);
            
            const response = await fetch('/question/answer', {
                method: 'POST',
                body: formData
            });
            
            // Redirect on success (handled by Flask)
            if (response.redirected) {
                window.location.href = response.url;
            } else {
                const data = await response.json();
                if (data.success) {
                    window.location.reload();
                } else {
                    showToast(data.error || '回答に失敗しました');
                }
            }
        } catch (err) {
            showToast('通信エラーが発生しました');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = '回答する';
        }
    });
}

// Toast Notification
function showToast(message) {
    // Remove existing toasts
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%) translateY(100px);
        background: var(--color-text);
        color: white;
        padding: 12px 20px;
        border-radius: var(--radius-md);
        font-size: 0.875rem;
        font-weight: 500;
        box-shadow: var(--shadow-lg);
        z-index: 2000;
        opacity: 0;
        transition: all 0.3s ease;
    `;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    // Animate in
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(-50%) translateY(0)';
    });
    
    // Animate out
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-50%) translateY(100px)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// HTML Escape Utility
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Format Date
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return 'たった今';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}時間前`;
    
    return date.toLocaleDateString('ja-JP', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Initialize date formatting on page load
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-date]').forEach(el => {
        el.textContent = formatDate(el.dataset.date);
    });
});

// Category badge class helper
function getCategoryBadgeClass(category) {
    const map = {
        '勉強・学習': 'badge--study',
        '学校生活': 'badge--school',
        '進路・受験': 'badge--career',
        '部活動': 'badge--club',
        '趣味・雑談': 'badge--hobby',
        'その他': 'badge--other',
        '今日の質問': 'badge--question'
    };
    return map[category] || 'badge--other';
}

// Export for use in templates
window.AppUtils = {
    escapeHtml,
    formatDate,
    getCategoryBadgeClass,
    showToast
};