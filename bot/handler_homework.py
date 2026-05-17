"""Homework demo booking flow for LINE."""

from __future__ import annotations

from services.homework_demo import parse_student_identity
from services.homework_demo_presenters import (
    build_homework_booking_list_flex,
    build_homework_date_flex,
    build_homework_slot_flex,
    build_homework_success_flex,
    build_homework_ta_flex,
)


class HandlerHomeworkMixin:
    """Encapsulate `/homework` register/cancel/list flows."""

    def _handle_homework_profile_update(self, user_id: str, reply_token: str) -> list:
        if not self.homework_booking_service or not self.homework_booking_service.is_enabled():
            return self._reply(reply_token, "Homework Demo 登記功能尚未啟用。")
        profile = self.queue_manager.db.get_homework_user_profile(user_id)
        current_label = ""
        if profile is not None:
            current_label = f"{profile.student_id} {profile.student_name}".strip()
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_profile_register",
                "next_action": "register_profile",
            },
        )
        if current_label:
            return self._reply(
                reply_token,
                f"目前 Homework 登記資料為：{current_label}\n請重新輸入 `<學號> <姓名>`，例如：`114106123 王小明` 以覆蓋資料。\n（請注意若已有預約請「先取消」並重新登記資料後再預約）",
            )
        return self._reply(
            reply_token,
            "請輸入 `<學號> <姓名>` 來完成 Homework 登記，例如：`114106123 王小明`。",
        )

    def _handle_homework_register(self, user_id: str, reply_token: str) -> list:
        if not self.homework_booking_service or not self.homework_booking_service.is_enabled():
            return self._reply(reply_token, "Homework Demo 登記功能尚未啟用。")
        student = self._get_homework_student(user_id)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="register")
        return self._begin_homework_register(user_id, reply_token, student)

    def _handle_homework_cancel(self, user_id: str, reply_token: str) -> list:
        if not self.homework_booking_service or not self.homework_booking_service.is_enabled():
            return self._reply(reply_token, "Homework Demo 取消功能尚未啟用。")
        student = self._get_homework_student(user_id)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="cancel")
        return self._begin_homework_cancel(user_id, reply_token, student)

    def _handle_homework_list(self, user_id: str, reply_token: str) -> list:
        if not self.homework_booking_service or not self.homework_booking_service.is_enabled():
            return self._reply(reply_token, "Homework Demo 查詢功能尚未啟用。")
        student = self._get_homework_student(user_id)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="list")
        return self._begin_homework_list(user_id, reply_token, student)

    def _capture_homework_input(self, user_id: str, text: str, reply_token: str) -> list:
        state = self._get_pending_state(user_id, "homework")
        state_type = state.get("type", "")
        if text.startswith("homework:register:ta:"):
            return self._capture_homework_ta(user_id, text, reply_token, state)
        if text.startswith("homework:register:date:"):
            return self._capture_homework_date(user_id, text, reply_token, state)
        if text.startswith("homework:register:slot:"):
            return self._capture_homework_slot(user_id, text, reply_token, state)
        if text.startswith("homework:cancel:booking:"):
            return self._capture_homework_cancel_selection(user_id, text, reply_token, state)
        if state_type == "homework_profile_register":
            return self._capture_homework_profile_registration(user_id, text, reply_token, state)
        return self._reply(reply_token, "Homework Demo 流程已失效，請重新輸入指令。")

    def _capture_homework_profile_registration(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        student = parse_student_identity(text)
        if student is None:
            return self._reply(reply_token, "格式錯誤，請輸入 `<學號> <姓名>`，例如：`114106123 王小明`。")
        self.queue_manager.db.upsert_homework_user_profile(
            user_id,
            student.student_id,
            student.student_name,
        )
        next_action = str(state.get("next_action") or "register")
        if next_action == "register_profile":
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, f"已更新 Homework 登記：{student.display_label}")
        if next_action == "cancel":
            return self._begin_homework_cancel(user_id, reply_token, student, registered_now=True)
        if next_action == "list":
            return self._begin_homework_list(user_id, reply_token, student, registered_now=True)
        return self._begin_homework_register(user_id, reply_token, student, registered_now=True)

    def _begin_homework_register(
        self,
        user_id: str,
        reply_token: str,
        student,
        *,
        registered_now: bool = False,
    ) -> list:
        ta_options = self.homework_booking_service.list_ta_options(student)
        if len(ta_options) == 1 and ta_options[0].selectable:
            ta_name = ta_options[0].ta_name
            date_options = self.homework_booking_service.list_date_options(student=student, ta_name=ta_name)
            self._set_pending_state(
                user_id,
                "homework",
                {
                    "type": "homework_register_date",
                    "student_id": student.student_id,
                    "student_name": student.student_name,
                    "ta_name": ta_name,
                },
            )
            messages = []
            if registered_now:
                messages.append({"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"})
            messages.extend(build_homework_date_flex(date_options, ta_name=ta_name))
            return self._reply_messages(reply_token, messages)
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_register_ta",
                "student_id": student.student_id,
                "student_name": student.student_name,
            },
        )
        messages = []
        if registered_now:
            messages.append({"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"})
        messages.extend(build_homework_ta_flex(ta_options))
        return self._reply_messages(reply_token, messages)

    def _begin_homework_cancel(
        self,
        user_id: str,
        reply_token: str,
        student,
        *,
        registered_now: bool = False,
    ) -> list:
        bookings = self.homework_booking_service.list_bookings(student)
        if not bookings:
            self._clear_pending_state(user_id, "homework")
            if registered_now:
                return self._reply_messages(
                    reply_token,
                    [
                        {"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"},
                        {"type": "text", "text": "目前查無預約資料。"},
                    ],
                )
            return self._reply(reply_token, "目前查無預約資料。")
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_cancel_select",
                "student_id": student.student_id,
                "student_name": student.student_name,
            },
        )
        messages = []
        if registered_now:
            messages.append({"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"})
        messages.extend(build_homework_booking_list_flex(bookings, mode="cancel"))
        return self._reply_messages(reply_token, messages)

    def _begin_homework_list(
        self,
        user_id: str,
        reply_token: str,
        student,
        *,
        registered_now: bool = False,
    ) -> list:
        bookings = self.homework_booking_service.list_bookings(student)
        if not bookings:
            self._clear_pending_state(user_id, "homework")
            if registered_now:
                return self._reply_messages(
                    reply_token,
                    [
                        {"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"},
                        {"type": "text", "text": "目前查無預約資料。"},
                    ],
                )
            return self._reply(reply_token, "目前查無預約資料。")
        self._clear_pending_state(user_id, "homework")
        messages = []
        if registered_now:
            messages.append({"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"})
        messages.extend(build_homework_booking_list_flex(bookings, mode="list"))
        return self._reply_messages(reply_token, messages)

    def _capture_homework_ta(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        prefix = "homework:register:ta:"
        if not text.startswith(prefix):
            return self._reply(reply_token, "請從卡片中選擇助教。")
        ta_name = text.removeprefix(prefix)
        student = self._resolve_homework_student_from_state_or_binding(user_id, state)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="register")
        date_options = self.homework_booking_service.list_date_options(student=student, ta_name=ta_name)
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_register_date",
                "student_id": student.student_id,
                "student_name": student.student_name,
                "ta_name": ta_name,
            },
        )
        return self._reply_messages(reply_token, build_homework_date_flex(date_options, ta_name=ta_name))

    def _capture_homework_date(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        prefix = "homework:register:date:"
        if not text.startswith(prefix):
            return self._reply(reply_token, "請從卡片中選擇日期。")
        date_payload = text.removeprefix(prefix)
        student = self._resolve_homework_student_from_state_or_binding(user_id, state)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="register")
        ta_name = str(state.get("ta_name") or "")
        iso_date = date_payload
        if ":" in date_payload:
            ta_name, iso_date = date_payload.split(":", 1)
        if not ta_name:
            ta_options = self.homework_booking_service.list_ta_options(student)
            selectable_tas = [option for option in ta_options if option.selectable]
            if len(selectable_tas) == 1:
                ta_name = selectable_tas[0].ta_name
            else:
                self._set_pending_state(
                    user_id,
                    "homework",
                    {
                        "type": "homework_register_ta",
                        "student_id": student.student_id,
                        "student_name": student.student_name,
                    },
                )
                return self._reply_messages(reply_token, build_homework_ta_flex(ta_options))
        slot_options = self.homework_booking_service.list_slot_options(
            student=student,
            ta_name=ta_name,
            iso_date=iso_date,
        )
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_register_slot",
                "student_id": student.student_id,
                "student_name": student.student_name,
                "ta_name": ta_name,
                "iso_date": iso_date,
            },
        )
        return self._reply_messages(
            reply_token,
            build_homework_slot_flex(slot_options, ta_name=ta_name, iso_date=iso_date),
        )

    def _capture_homework_slot(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        prefix = "homework:register:slot:"
        if not text.startswith(prefix):
            return self._reply(reply_token, "請從卡片中選擇時段。")
        booking_key = text.removeprefix(prefix)
        student = self._resolve_homework_student_from_state_or_binding(user_id, state)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="register")
        ta_name = str(state.get("ta_name") or self._ta_name_from_booking_key(booking_key) or "")
        result = self.homework_booking_service.book_slot(
            student=student,
            ta_name=ta_name,
            booking_key=booking_key,
        )
        self._clear_pending_state(user_id, "homework")
        if result.status != "success" or result.booking is None:
            return self._reply(reply_token, result.message)
        self.queue_manager.db.log_event(
            "homework_register",
            user_id,
            "homework_demo",
            (
                f"student={student.display_label}; "
                f"ta={result.booking.ta_name}; "
                f"date={result.booking.iso_date}; "
                f"slot={result.booking.time_slot}"
            ),
        )
        return self._reply_messages(
            reply_token,
            [build_homework_success_flex(title="預約完成", booking=result.booking, student_label=student.display_label)],
        )

    def _capture_homework_cancel_selection(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        prefix = "homework:cancel:booking:"
        if not text.startswith(prefix):
            return self._reply(reply_token, "請從卡片中選擇要取消的預約。")
        student = self._resolve_homework_student_from_state_or_binding(user_id, state)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="cancel")
        result = self.homework_booking_service.cancel_booking(student=student, booking_key=text.removeprefix(prefix))
        self._clear_pending_state(user_id, "homework")
        if result.status != "success" or result.booking is None:
            return self._reply(reply_token, result.message)
        self.queue_manager.db.log_event(
            "homework_cancel",
            user_id,
            "homework_demo",
            (
                f"student={student.display_label}; "
                f"ta={result.booking.ta_name}; "
                f"date={result.booking.iso_date}; "
                f"slot={result.booking.time_slot}"
            ),
        )
        return self._reply_messages(
            reply_token,
            [build_homework_success_flex(title="取消成功", booking=result.booking, student_label=student.display_label)],
        )

    def _get_homework_student(self, user_id: str):
        profile = self.queue_manager.db.get_homework_user_profile(user_id)
        if profile is None:
            return None
        return parse_student_identity(f"{profile.student_id} {profile.student_name}")

    def _resolve_homework_student_from_state_or_binding(self, user_id: str, state: dict):
        student = parse_student_identity(f"{state.get('student_id', '')} {state.get('student_name', '')}")
        if student is not None:
            return student
        return self._get_homework_student(user_id)

    def _ta_name_from_booking_key(self, booking_key: str) -> str:
        parts = str(booking_key or "").split("|", 2)
        if len(parts) < 3:
            return ""
        return parts[0]

    def _prompt_homework_profile_registration(self, user_id: str, reply_token: str, *, action: str) -> list:
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_profile_register",
                "next_action": action,
            },
        )
        return self._reply(
            reply_token,
            "你尚未完成 Homework 登記資料登記，請輸入 `<學號> <姓名>`，例如：`114106123 王小明`。",
        )
