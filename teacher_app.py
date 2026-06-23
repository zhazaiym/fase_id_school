import flet as ft
import requests

from database import get_class_attendance, get_students_by_class

SERVER_URL = "http://127.0.0.1:8000"


def main(page: ft.Page):
    page.title = "Кабинет учителя"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window_width = 420
    page.window_height = 800

    class_input = ft.TextField(label="Класс (например: 10А)", width=320)
    password_input = ft.TextField(label="Пароль", password=True, width=320)
    error_text = ft.Text("", color="red")

    student_list = ft.ListView(expand=1, spacing=5)
    attendance_list = ft.ListView(expand=1, spacing=5)

    def update_teacher_ui(class_name):
        students = get_students_by_class(class_name)
        student_list.controls.clear()
        for name, parent_code in students:
            student_list.controls.append(ft.Row([
                ft.Text(f"{name}: ", weight="bold"),
                ft.Text(parent_code if parent_code else "Кода нет"),
            ]))

        attendance = get_class_attendance(class_name)
        attendance_list.controls.clear()
        if not attendance:
            attendance_list.controls.append(ft.Text("Сегодня записей нет."))
        else:
            for name, status, time_text in attendance:
                color = "green" if status == "keldi" else "red"
                status_text = "Пришел" if status == "keldi" else "Ушел"
                attendance_list.controls.append(ft.Row([
                    ft.Text(name),
                    ft.Text(f"{status_text} ({time_text})", color=color),
                ]))
        page.update()

    def show_dashboard(class_name):
        page.clean()
        page.add(ft.Text(f"Класс: {class_name}", size=20, weight="bold"))
        page.add(ft.Text("Список учеников:", weight="bold"), student_list)
        page.add(ft.Text("Журнал посещаемости:", weight="bold"), attendance_list)
        update_teacher_ui(class_name)

    def login_click(e):
        try:
            response = requests.post(
                f"{SERVER_URL}/api/login",
                data={"class_name": class_input.value, "password": password_input.value},
                timeout=5,
            )
            if response.json().get("status") == "success":
                show_dashboard(class_input.value)
            else:
                error_text.value = "Пароль или класс неверный!"
                page.update()
        except Exception:
            error_text.value = "Нет связи с сервером!"
            page.update()

    page.add(class_input, password_input, ft.FilledButton("Войти", on_click=login_click), error_text)


if __name__ == "__main__":
    ft.run(main)
