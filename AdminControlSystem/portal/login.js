document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const loginBtn = document.getElementById('loginBtn');
    const errorMessage = document.getElementById('errorMessage');

    // Check if already logged in
    const token = localStorage.getItem('token');
    if (token) {
        verifyToken(token);
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        
        // UI Feedback
        loginBtn.classList.add('loading');
        loginBtn.disabled = true;
        errorMessage.classList.remove('show');
        
        try {
            const formData = new FormData();
            formData.append('username', username);
            formData.append('password', password);
            
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                body: formData
            });
            
            if (response.ok) {
                const data = await response.json();
                localStorage.setItem('token', data.access_token);
                window.location.href = '/';
            } else {
                showError();
            }
        } catch (error) {
            console.error('Login error:', error);
            showError();
        } finally {
            loginBtn.classList.remove('loading');
            loginBtn.disabled = false;
        }
    });

    function showError() {
        errorMessage.classList.add('show');
    }

    async function verifyToken(token) {
        try {
            const response = await fetch('/api/auth/verify', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            if (response.ok) {
                window.location.href = '/';
            } else {
                localStorage.removeItem('token');
            }
        } catch (error) {
            localStorage.removeItem('token');
        }
    }
});
