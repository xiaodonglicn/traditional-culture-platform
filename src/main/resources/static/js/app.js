// API 基础地址
const API_BASE = '/api';

// ========== 页面切换 ==========
document.querySelectorAll('nav a').forEach(link => {
    link.addEventListener('click', function(e) {
        e.preventDefault();

        // 切换 tab 激活状态
        document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
        this.classList.add('active');

        // 切换内容
        const tab = this.dataset.tab;
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        document.getElementById(`${tab}-tab`).classList.add('active');

        // 加载对应数据
        if (tab === 'daoism') loadDaoismQuotes('all');
        if (tab === 'elements') loadElements();
    });
});

// ========== 加载生肖列表 ==========
async function loadZodiacs() {
    try {
        const response = await fetch(`${API_BASE}/fortune/zodiacs`);
        const data = await response.json();
        if (data.code === 200) {
            const select = document.getElementById('zodiac-select');
            data.data.forEach(zodiac => {
                const option = document.createElement('option');
                option.value = zodiac;
                option.textContent = zodiac;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('加载生肖失败:', error);
    }
}

// ========== 获取运势 ==========
document.getElementById('get-fortune-btn').addEventListener('click', async function() {
    const zodiac = document.getElementById('zodiac-select').value;
    if (!zodiac) {
        alert('请先选择您的生肖 🐉');
        return;
    }

    try {
        this.disabled = true;
        this.textContent = '加载中...';

        const response = await fetch(`${API_BASE}/fortune/daily?zodiac=${encodeURIComponent(zodiac)}`);
        const data = await response.json();

        if (data.code === 200) {
            displayFortune(data.data);
        } else {
            alert('获取运势失败，请稍后再试');
        }
    } catch (error) {
        console.error('获取运势失败:', error);
        alert('网络错误，请检查服务是否启动');
    } finally {
        this.disabled = false;
        this.textContent = '查看今日运势';
    }
});

function displayFortune(fortune) {
    const resultDiv = document.getElementById('fortune-result');
    resultDiv.style.display = 'block';

    document.getElementById('fortune-date').textContent = `📅 ${fortune.date}`;
    document.getElementById('fortune-zodiac').textContent = `🐉 ${fortune.zodiac}`;

    const levelEl = document.getElementById('fortune-level');
    levelEl.textContent = fortune.luckLevel;
    levelEl.dataset.level = fortune.luckLevel;

    document.getElementById('fortune-score').textContent = fortune.luckScore;
    document.getElementById('fortune-summary').textContent = fortune.summary;
    document.getElementById('fortune-career').textContent = fortune.career;
    document.getElementById('fortune-love').textContent = fortune.love;
    document.getElementById('fortune-wealth').textContent = fortune.wealth;

    // 幸运色
    const colorsContainer = document.getElementById('fortune-colors');
    colorsContainer.innerHTML = '';
    fortune.luckyColors.forEach(color => {
        const span = document.createElement('span');
        span.textContent = color;
        span.style.background = getColorBg(color);
        colorsContainer.appendChild(span);
    });

    // 幸运数字
    document.getElementById('fortune-numbers').textContent = fortune.luckyNumbers.join('、');
    document.getElementById('fortune-advice').textContent = fortune.advice;
}

function getColorBg(color) {
    const map = {
        '红色': '#ff6b6b',
        '金色': '#ffd700',
        '蓝色': '#4a9eff',
        '绿色': '#51cf66',
        '紫色': '#9775fa',
        '白色': '#f8f9fa',
        '黑色': '#343a40',
        '黄色': '#ffd93d',
        '棕色': '#a67c52'
    };
    return map[color] || '#ddd';
}

// ========== 道家名言 ==========
async function loadDaoismQuotes(category = 'all') {
    try {
        let url = `${API_BASE}/daoism/quotes`;
        if (category !== 'all') {
            url = `${API_BASE}/daoism/category/${category}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        if (data.code === 200) {
            renderQuotes(data.data);
        }
    } catch (error) {
        console.error('加载名言失败:', error);
    }
}

function renderQuotes(quotes) {
    const container = document.getElementById('daoism-quotes');
    if (quotes.length === 0) {
        container.innerHTML = '<p style="text-align:center;color:#8b7a6a;">暂无相关名言</p>';
        return;
    }

    container.innerHTML = quotes.map(quote => `
        <div class="quote-card">
            <div class="quote-source">📖 ${quote.source} · ${quote.chapter}</div>
            <div class="quote-original">${quote.original}</div>
            <div class="quote-translation">📝 ${quote.translation}</div>
            <div class="quote-interpretation">💭 ${quote.interpretation}</div>
            <span class="quote-category"># ${quote.category}</span>
        </div>
    `).join('');
}

// 随机名言
document.getElementById('random-quote-btn').addEventListener('click', async function() {
    try {
        const response = await fetch(`${API_BASE}/daoism/random`);
        const data = await response.json();
        if (data.code === 200) {
            renderQuotes([data.data]);
        }
    } catch (error) {
        console.error('获取随机名言失败:', error);
    }
});

// 分类筛选
document.getElementById('category-select').addEventListener('change', function() {
    loadDaoismQuotes(this.value);
});

// 加载分类列表
async function loadCategories() {
    try {
        const response = await fetch(`${API_BASE}/daoism/categories`);
        const data = await response.json();
        if (data.code === 200) {
            const select = document.getElementById('category-select');
            data.data.forEach(category => {
                const option = document.createElement('option');
                option.value = category;
                option.textContent = category;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('加载分类失败:', error);
    }
}

// ========== 五行学说 ==========
async function loadElements() {
    try {
        const response = await fetch(`${API_BASE}/elements/all`);
        const data = await response.json();
        if (data.code === 200) {
            renderElements(data.data);
        }
    } catch (error) {
        console.error('加载五行数据失败:', error);
    }
}

function renderElements(elements) {
    const grid = document.getElementById('elements-grid');
    grid.innerHTML = elements.map(el => `
        <div class="element-card">
            <span class="element-icon">${getElementIcon(el.element)}</span>
            <div class="element-name">${el.element}</div>
            <div class="element-desc">${el.description}</div>
            <div class="element-detail">方位：${el.direction} · 季节：${el.season}</div>
            <div class="element-color" style="background:${getElementColor(el.color)};"></div>
            <div class="element-detail" style="margin-top:6px;font-size:11px;">
                相生：${el.generates} | 相克：${el.restricts}
            </div>
        </div>
    `).join('');
}

function getElementIcon(element) {
    const map = {
        '金': '⚔️',
        '木': '🌳',
        '水': '💧',
        '火': '🔥',
        '土': '⛰️'
    };
    return map[element] || '🌐';
}

function getElementColor(color) {
    const map = {
        '白色': '#f0f0f0',
        '青色': '#7bc5a0',
        '黑色': '#4a4a4a',
        '赤色': '#e74c3c',
        '黄色': '#f1c40f'
    };
    return map[color] || '#ddd';
}

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', function() {
    loadZodiacs();
    loadCategories();
    loadDaoismQuotes('all');
    loadElements();
});