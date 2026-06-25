import html
from datetime import datetime
from urllib.parse import quote

from database import get_all_students_list, get_recent_attendance


def page(title, body):
    return f"""
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        <link rel="stylesheet" href="/static/styles.css">
    </head>
    <body><main>{body}</main></body>
    </html>
    """


def esc(value):
    return html.escape(str(value or ""))


def url_value(value):
    return quote(str(value or ""), safe="")


def students_rows():
    rows = []
    for name, class_name, photo_path, parent_name, parent_code in get_all_students_list():
        rows.append(f"""
        <tr>
            <td><img class="photo" src="/{esc(photo_path)}" alt=""></td>
            <td>{esc(name)}</td>
            <td>{esc(class_name)}</td>
            <td>{esc(parent_name)}</td>
            <td>{esc(parent_code)}</td>
            <td class="actions">
                <a class="btn light" href="/edit/{url_value(name)}">Изменить</a>
                <a class="btn red" href="/delete/{url_value(name)}">Удалить</a>
            </td>
        </tr>
        """)
    if not rows:
        return "<tr><td colspan='6' class='muted'>Пока учеников нет</td></tr>"
    return "".join(rows)


def attendance_rows():
    rows = []
    for name, class_name, status, timestamp, parent_name, parent_code in get_recent_attendance(30):
        status_text = "Пришел" if status == "keldi" else "Ушел"
        rows.append(f"""
        <tr>
            <td>{esc(name)}</td>
            <td>{esc(class_name)}</td>
            <td>{status_text}</td>
            <td>{esc(timestamp)}</td>
            <td>{esc(parent_name)} <span class="muted">({esc(parent_code)})</span></td>
        </tr>
        """)
    if not rows:
        return "<tr><td colspan='5' class='muted'>Отчетов пока нет</td></tr>"
    return "".join(rows)


def home_dashboard():
    students_count = len(get_all_students_list())
    recent = get_recent_attendance(200)
    today = datetime.now().strftime("%Y-%m-%d")
    today_in = sum(
        1
        for _, _, status, timestamp, _, _ in recent
        if status == "keldi" and str(timestamp).startswith(today)
    )
    today_out = sum(
        1
        for _, _, status, timestamp, _, _ in recent
        if status == "ketti" and str(timestamp).startswith(today)
    )

    return f"""
        <div class="grid home-stats">
            <div class="stat green" data-icon="👥">
                <strong>{students_count}</strong>
                <span class="muted">Ученики в базе</span>
                <div class="trend">
                    <svg viewBox="0 0 120 50"><path d="M5 39 L34 29 L55 15 L78 22 L110 4" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="110" cy="4" r="6" fill="#22c55e"/></svg>
                </div>
                <span class="pill"><b>+{students_count}</b> всего</span>
            </div>
            <div class="stat blue" data-icon="👤">
                <strong>{today_in}</strong>
                <span class="muted">Сегодня пришли</span>
                <div class="trend">
                    <svg viewBox="0 0 120 50"><path d="M6 39 L34 25 L60 13 L85 21 L111 4" fill="none" stroke="#2563eb" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="111" cy="4" r="6" fill="#2563eb"/></svg>
                </div>
                <span class="pill"><b>+{today_in}</b> за сегодня</span>
            </div>
            <div class="stat red" data-icon="👤">
                <strong>{today_out}</strong>
                <span class="muted">Сегодня ушли</span>
                <div class="trend">
                    <svg viewBox="0 0 120 50"><path d="M8 29 L42 29 L76 29 L112 29" fill="none" stroke="#ef4444" stroke-width="5" stroke-linecap="round"/><circle cx="42" cy="29" r="5" fill="#ef4444"/><circle cx="76" cy="29" r="5" fill="#ef4444"/></svg>
                </div>
                <span class="pill"><b>{today_out}</b> за сегодня</span>
            </div>
        </div>
    """


def home_view():
    return """
        <div class="home-shell">
            <div class="home-top">
                <div class="notify">♢</div>
                <div class="avatar">●</div>
            </div>
            <section class="hero">
                <div class="shield">▣</div>
                <h1>School Face ID <span class="spark">✦</span></h1>
                <p>Камера, ученики, родители и отчеты в одном месте.</p>
                <div class="hero-line"></div>
            </section>
            <div class="grid nav-grid">
                <a class="nav-card green" data-icon="👥" href="/students">
                    <strong>Ученики</strong>
                    <span>Просмотр и управление учениками</span>
                </a>
                <a class="nav-card blue" data-icon="📷" href="/camera">
                    <strong>Камера</strong>
                    <span>Просмотр в реальном времени</span>
                </a>
                <a class="nav-card purple" data-icon="📄" href="/list">
                    <strong>List / Общий отчет</strong>
                    <span>Отчеты и статистика</span>
                </a>
                <a class="nav-card orange" data-icon="👥" href="/parent">
                    <strong>Родитель</strong>
                    <span>Информация о родителях</span>
                </a>
            </div>
    """ + home_dashboard() + """
            <div class="home-footer">
                <b>Face ID School System</b><br>
                Безопасность · Точность · Удобство
            </div>
            <div class="decor-dots left"></div>
            <div class="decor-dots right"></div>
        </div>
    """


def list_view():
    return """
        <form class="inline-form clear-attendance-form" action="/clear-attendance" method="post" onsubmit="return confirm('Ochistka: kelgen/ketken jurnalyn ochurobuzbu?')">
            <button class="btn red" type="submit">Очистка</button>
        </form>
        <div class="top">
            <a class="btn light" href="/">Назад</a>
            <a class="btn" href="/camera">Камера</a>
            <a class="btn green" href="/students">Ученики</a>
        </div>
        <h1>List / Общий отчет</h1>
        <table>
            <thead><tr><th>Ученик</th><th>Класс</th><th>Статус</th><th>Время</th><th>Родитель</th></tr></thead>
            <tbody>""" + attendance_rows() + """</tbody>
        </table>
    """


def students_view():
    return """
        <div class="top">
            <a class="btn light" href="/">Назад</a>
            <a class="btn" href="/camera">Камера</a>
        </div>
        <h1>Ученики</h1>
        <div class="panel">
            <h2>Добавить ученика</h2>
            <form action="/add" method="post" enctype="multipart/form-data">
                <label>Имя ученика</label>
                <input name="name" required placeholder="Например: Иван Иванов">
                <label>Класс</label>
                <input name="class_name" required placeholder="Например: 11А">
                <label>Родитель</label>
                <input name="parent_name" required placeholder="Имя родителя">
                <label>Код родителя для входа</label>
                <input name="parent_code" required placeholder="Например: parent_ivanov">
                <label>Фото ученика</label>
                <input type="file" name="photo" accept="image/*" required>
                <button class="btn green" type="submit">Добавить в базу</button>
            </form>
        </div>
        <h2>Ученики в базе</h2>
        <table>
            <thead><tr><th>Фото</th><th>Имя</th><th>Класс</th><th>Родитель</th><th>Код</th><th>Действие</th></tr></thead>
            <tbody>""" + students_rows() + """</tbody>
        </table>
    """


def edit_student_view(student):
    name, class_name, photo_path, parent_name, parent_code, _ = student
    return f"""
        <div class="top">
            <a class="btn light" href="/students">Назад</a>
            <a class="btn" href="/camera">Камера</a>
        </div>
        <h1>Изменить ученика</h1>
        <div class="panel">
            <form action="/edit/{url_value(name)}" method="post" enctype="multipart/form-data">
                <label>Имя ученика</label>
                <input name="name" value="{esc(name)}" required>
                <label>Класс</label>
                <input name="class_name" value="{esc(class_name)}" required>
                <label>Родитель</label>
                <input name="parent_name" value="{esc(parent_name)}" required>
                <label>Код родителя для входа</label>
                <input name="parent_code" value="{esc(parent_code)}" required>
                <label>Новое фото ученика</label>
                <input type="file" name="photo" accept="image/*">
                <div class="edit-photo">
                    <img class="photo" src="/{esc(photo_path)}" alt="">
                    <span class="muted">Если фото не выбрать, останется старое.</span>
                </div>
                <button class="btn green" type="submit">Сохранить</button>
            </form>
        </div>
    """


def parent_login_view(name="", code=""):
    return f"""
        <div class="top"><a class="btn light" href="/">Назад</a></div>
        <h1>Кабинет родителя</h1>
        <div class="panel">
            <form action="/parent" method="get">
                <label>Имя родителя</label>
                <input name="name" value="{esc(name)}" placeholder="Введите имя родителя" required>
                <label>Код родителя</label>
                <input name="code" value="{esc(code)}" placeholder="Введите код родителя" required>
                <button class="btn" type="submit">Войти и показать отчет</button>
            </form>
        </div>
    """


def parent_report_view(rows):
    return f"""
        <div class="top">
            <a class="btn light" href="/">Назад</a>
            <a class="btn light" href="/parent">Другой родитель</a>
        </div>
        <h1>Отчет ребенка</h1>
        <table>
            <thead><tr><th>Ученик</th><th>Класс</th><th>Статус</th><th>Время</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    """
