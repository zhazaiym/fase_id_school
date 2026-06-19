import flet as ft
import requests
# database.py ичиндеги функцияларды импорттоо
from database import get_students_by_class, get_class_attendance

SERVER_URL = "http://127.0.0.1:8000"


def main(page: ft.Page):
    page.title = "Мугалимдер кабинети"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 400
    page.window_height = 800

    class_input = ft.TextField(label="Класс (Мисалы: 10 b)", width=300)
    password_input = ft.TextField(label="Пароль", password=True, width=300)
    error_text = ft.Text("", color="red")

    # Тизмелерди глобалдык деңгээлде эмес, main ичинде түзөбүз
    student_list = ft.ListView(expand=1, spacing=5)
    attendance_list = ft.ListView(expand=1, spacing=5)

    def update_teacher_ui(class_name):
        # 1. Окуучулардын тизмесин көрсөтүү
        students = get_students_by_class(class_name)
        student_list.controls.clear()
        for name, chat_id in students:
            student_list.controls.append(ft.Row([
                ft.Text(f"{name}: ", weight="bold"),
                ft.Text(chat_id if chat_id else "ID жок")
            ]))

        # 2. Келди/Кетти журналын көрсөтүү
        attendance = get_class_attendance(class_name)
        attendance_list.controls.clear()
        if not attendance:
            attendance_list.controls.append(ft.Text("Бүгүн эч ким келген жок."))
        else:
            for name, status, time in attendance:
                color = "green" if status == "keldi" else "red"
                icon = "✅" if status == "keldi" else "🚪"
                attendance_list.controls.append(ft.Row([
                    ft.Text(name),
                    ft.Text(f"{icon} {status} ({time})", color=color)
                ]))
        page.update()

    def show_dashboard(class_name):
        page.clean()
        page.add(ft.Text(f"🏢 Класс: {class_name}", size=20, weight="bold"))
        page.add(ft.Text("👤 Окуучулар тизмеси:", weight="bold"), student_list)
        page.add(ft.Text("📅 Келди-кетти журналы:", weight="bold"), attendance_list)


        # UIди жаңыртуу
        update_teacher_ui(class_name)


    def login_click(e):
        try:
            res = requests.post(f"{SERVER_URL}/api/login",
                                data={"class_name": class_input.value, "password": password_input.value},
                                timeout=5)
            if res.json().get("status") == "success":
                show_dashboard(class_input.value)
            else:
                error_text.value = "Пароль же класс туура эмес!"
                page.update()
        except:
            error_text.value = "Сервер менен байланыш жок!"
            page.update()

    page.add(class_input, password_input, ft.FilledButton("Кирүү", on_click=login_click), error_text)


if __name__ == "__main__":
    ft.run(main)
