document.addEventListener('DOMContentLoaded', function () {
    // --- THEME SWITCHER LOGIC ---
    const themeSwitcherBtn = document.getElementById('theme-switcher-btn');
    const themeIcon = document.getElementById('theme-icon');

    function getCookie(name) {
        var m = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
        return m ? m[2] : null;
    }
    const getStoredTheme = () => getCookie('gh_theme') || localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const setStoredTheme = theme => {
        localStorage.setItem('theme', theme);
        document.cookie = 'gh_theme=' + theme + ';path=/;max-age=31536000;SameSite=Lax';
    };

    // Function to update the switcher icon based on the current theme
    const updateIcon = (theme) => {
        themeIcon.className = 'bi'; // Reset classes
        if (theme === 'dark') {
            themeIcon.classList.add('bi-sun-fill');
        } else {
            themeIcon.classList.add('bi-moon-stars-fill');
        }
    };

    // Set the correct icon on initial page load
    updateIcon(getStoredTheme());

    // Add click listener to the theme switcher button
    if (themeSwitcherBtn) {
        themeSwitcherBtn.addEventListener('click', () => {
            const currentTheme = getStoredTheme();
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            setStoredTheme(newTheme);
            document.documentElement.setAttribute('data-bs-theme', newTheme);
            updateIcon(newTheme);
        });
    }

    // --- PARTICLES.JS CONFIGURATION ---
    if (document.getElementById('particles-js')) {
        particlesJS('particles-js', {
            "particles": { "number": { "value": 50, "density": { "enable": true, "value_area": 800 } }, "color": { "value": "#c4a668" }, "shape": { "type": "polygon", "stroke": { "width": 1, "color": "#c4a668" }, "polygon": { "nb_sides": 6 } }, "opacity": { "value": 0.2, "random": true, "anim": { "enable": true, "speed": 0.5, "opacity_min": 0.05, "sync": false } }, "size": { "value": 4, "random": true }, "line_linked": { "enable": true, "distance": 180, "color": "#c4a668", "opacity": 0.15, "width": 1 }, "move": { "enable": true, "speed": 0.8, "direction": "none", "random": true, "straight": false, "out_mode": "out" } },
            "interactivity": { "detect_on": "canvas", "events": { "onhover": { "enable": true, "mode": "bubble" } }, "modes": { "bubble": { "distance": 200, "size": 6, "duration": 2, "opacity": 0.6 } } },
            "retina_detect": true
        });
    }
});
