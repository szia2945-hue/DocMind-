// ===========================================
// main.js
// DocMind ke tamam pages ke liye common JavaScript helpers.
// Page-specific logic (jaise chat.html ka AJAX code) apne
// respective templates ke {% block scripts %} me hai.
// ===========================================

// Flash messages ko kuch second baad automatically fade out karo
document.addEventListener("DOMContentLoaded", function () {
    const flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (flash) {
        setTimeout(function () {
            flash.style.transition = "opacity 0.5s ease";
            flash.style.opacity = "0";
            setTimeout(function () {
                flash.remove();
            }, 500);
        }, 5000); // 5 seconds ke baad fade start
    });
});

// Simple client-side check: PDF upload se pehle file size validate karo (10 MB)
document.addEventListener("DOMContentLoaded", function () {
    const pdfInput = document.getElementById("pdf_file");
    if (pdfInput) {
        pdfInput.addEventListener("change", function () {
            const maxSizeBytes = 10 * 1024 * 1024; // 10 MB
            if (pdfInput.files.length > 0 && pdfInput.files[0].size > maxSizeBytes) {
                alert("File is too large! Maximum allowed size is 10 MB.");
                pdfInput.value = "";
            }
        });
    }
});

// ===========================================
// Dark / Light theme toggle
// Preference localStorage me save hoti hai taake har page pe yaad rahe.
// ===========================================
document.addEventListener("DOMContentLoaded", function () {
    const toggleBtn = document.getElementById("theme-toggle-btn");
    if (!toggleBtn) return;

    toggleBtn.addEventListener("click", function () {
        const current = document.documentElement.getAttribute("data-theme") || "dark";
        const next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("docmind-theme", next);
    });
});
