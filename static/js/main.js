// Share document
function shareDoc(docId) {
    fetch(`/share/${docId}`)
        .then(res => res.json())
        .then(data => {
            navigator.clipboard.writeText(data.link);
            showToast('🔗 Share link copied! Expires in 24 hours.');
        })
        .catch(() => showToast('Failed to generate share link.'));
}

// AI Summarize
function summarizeDoc(docId, btn) {
    const box = document.getElementById(`summary-${docId}`);
    box.style.display = 'block';
    box.innerText = '🤖 AI is reading your document...';
    btn.disabled = true;
    btn.innerText = 'Loading...';

    fetch(`/summarize/${docId}`)
        .then(res => res.json())
        .then(data => {
            box.innerText = '🤖 ' + data.summary;
            btn.innerText = 'AI Summary';
            btn.disabled = false;
        })
        .catch(() => {
            box.innerText = 'Failed to summarize. Try again.';
            btn.innerText = 'AI Summary';
            btn.disabled = false;
        });
}

// Show filename after selection
function updateFileName(input) {
    const name = input.files[0]?.name;
    if (name) {
        document.getElementById('file-name').innerText = '✅ ' + name;
    }
}

// Toast notification
function showToast(message) {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.innerText = message;
        toast.style.display = 'block';
        setTimeout(() => { toast.style.display = 'none'; }, 4000);
    }
}