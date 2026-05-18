"""Homework demo booking flow for LINE."""

from __future__ import annotations

from services.homework_demo import parse_student_identity
from services.homework_demo_presenters import (
    build_homework_booking_list_flex,
    build_homework_cancel_application_result_flex,
    build_homework_cancel_application_review_flex,
    build_homework_date_flex,
    build_homework_late_cancel_apply_flex,
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

    def _handle_homework_cancel_apply(self, user_id: str, reply_token: str) -> list:
        if not self.homework_booking_service or not self.homework_booking_service.is_enabled():
            return self._reply(reply_token, "Homework Demo 逾期取消申請功能尚未啟用。")
        student = self._get_homework_student(user_id)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="cancel_apply")
        return self._begin_homework_cancel_apply(user_id, reply_token, student)

    def _capture_homework_input(self, user_id: str, text: str, reply_token: str) -> list:
        state = self._get_pending_state(user_id, "homework")
        state_type = state.get("type", "")
        if text.startswith("homework:cancel:apply:review:approve:"):
            return self._capture_homework_cancel_apply_review_approve(user_id, text, reply_token)
        if text.startswith("homework:cancel:apply:review:reject:"):
            return self._capture_homework_cancel_apply_review_reject(user_id, text, reply_token)
        if text.startswith("homework:cancel:apply:booking:"):
            return self._capture_homework_cancel_apply_selection(user_id, text, reply_token, state)
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
        if state_type == "homework_cancel_apply_reason":
            return self._capture_homework_cancel_apply_reason(user_id, text, reply_token, state)
        if state_type == "homework_cancel_review_reject_reason":
            return self._capture_homework_cancel_apply_reject_reason(user_id, text, reply_token, state)
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
        if next_action == "cancel_apply":
            return self._begin_homework_cancel_apply(user_id, reply_token, student, registered_now=True)
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

    def _begin_homework_cancel_apply(
        self,
        user_id: str,
        reply_token: str,
        student,
        *,
        registered_now: bool = False,
    ) -> list:
        bookings = self.homework_booking_service.list_late_cancel_applicable_bookings(student)
        if not bookings:
            self._clear_pending_state(user_id, "homework")
            if registered_now:
                return self._reply_messages(
                    reply_token,
                    [
                        {"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"},
                        {"type": "text", "text": "目前沒有可申請逾期取消的預約。"},
                    ],
                )
            return self._reply(reply_token, "目前沒有可申請逾期取消的預約。")
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_cancel_apply_select",
                "student_id": student.student_id,
                "student_name": student.student_name,
            },
        )
        pending_booking_keys = {
            booking.booking_key
            for booking in bookings
            if self.queue_manager.db.get_pending_homework_cancel_application_by_booking_key(booking.booking_key) is not None
        }
        messages = []
        if registered_now:
            messages.append({"type": "text", "text": f"已完成 Homework 登記：{student.display_label}"})
        messages.extend(build_homework_late_cancel_apply_flex(bookings, pending_booking_keys=pending_booking_keys))
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

    def _capture_homework_cancel_apply_selection(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        prefix = "homework:cancel:apply:booking:"
        if not text.startswith(prefix):
            return self._reply(reply_token, "請從卡片中選擇要申請取消的預約。")
        student = self._resolve_homework_student_from_state_or_binding(user_id, state)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="cancel_apply")
        booking_key = text.removeprefix(prefix)
        booking = next(
            (item for item in self.homework_booking_service.list_late_cancel_applicable_bookings(student) if item.booking_key == booking_key),
            None,
        )
        if booking is None:
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "找不到可申請的預約資料，請重新操作。")
        if self.queue_manager.db.get_pending_homework_cancel_application_by_booking_key(booking_key) is not None:
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "這筆預約已送出逾期取消申請，請等待助教審核。")
        target_user_id = self.homework_booking_service.get_late_cancel_application_target(booking)
        if not target_user_id:
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "此助教尚未設定審核通知對象，請聯絡管理員。")
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_cancel_apply_reason",
                "student_id": student.student_id,
                "student_name": student.student_name,
                "booking_key": booking.booking_key,
                "sheet_name": booking.sheet_name,
                "target_user_id": target_user_id,
            },
        )
        return self._reply(reply_token, f"請輸入逾期取消理由：{booking.ta_name} {booking.iso_date} {booking.time_slot}")

    def _capture_homework_cancel_apply_reason(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        reason = str(text or "").strip()
        if not reason:
            return self._reply(reply_token, "取消理由不可為空，請重新輸入。")
        student = self._resolve_homework_student_from_state_or_binding(user_id, state)
        if student is None:
            return self._prompt_homework_profile_registration(user_id, reply_token, action="cancel_apply")
        booking_key = str(state.get("booking_key") or "")
        booking = next(
            (item for item in self.homework_booking_service.list_late_cancel_applicable_bookings(student) if item.booking_key == booking_key),
            None,
        )
        if booking is None:
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "找不到可申請的預約資料，請重新操作。")
        target_user_id = str(state.get("target_user_id") or self.homework_booking_service.get_late_cancel_application_target(booking))
        if not target_user_id:
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "此助教尚未設定審核通知對象，請聯絡管理員。")
        application = self.queue_manager.db.create_homework_cancel_application(
            student_user_id=user_id,
            student_id=student.student_id,
            student_name=student.student_name,
            booking_key=booking.booking_key,
            sheet_name=booking.sheet_name,
            booking_date=booking.iso_date,
            time_slot=booking.time_slot,
            reason=reason,
        )
        self._clear_pending_state(user_id, "homework")
        if application is None:
            return self._reply(reply_token, "這筆預約已經有待審核的取消申請，請稍候結果。")
        notify_result = self.notifier.push_flex(
            target_user_id,
            build_homework_cancel_application_review_flex(application=application.__dict__),
        )
        if notify_result.startswith("推播 Flex 失敗給 "):
            self.queue_manager.db.mark_homework_cancel_application_invalid(
                application.id,
                reviewed_by="system",
                review_reason="審核通知推播失敗，請學生重新送出申請。",
            )
            return self._reply(reply_token, "逾期取消申請送出失敗，請稍後再試。")
        self.queue_manager.db.log_event(
            "homework_cancel_apply",
            user_id,
            "homework_demo",
            f"student={student.display_label}; booking_key={booking.booking_key}; reason={reason}",
        )
        return self._reply(reply_token, "逾期取消申請已送出，請等待助教審核。")

    def _capture_homework_cancel_apply_review_approve(self, user_id: str, text: str, reply_token: str) -> list:
        application_id = self._parse_application_id(text, "homework:cancel:apply:review:approve:")
        if application_id is None:
            return self._reply(reply_token, "找不到指定的申請資料。")
        application = self.queue_manager.db.get_homework_cancel_application(application_id)
        if application is None or application.get("status") != "pending":
            return self._reply(reply_token, "這筆申請已經處理過或不存在。")
        if not self._is_homework_cancel_reviewer(user_id, application):
            return self._reply(reply_token, "你不是這筆申請的審核對象。")
        student = parse_student_identity(f"{application.get('student_id', '')} {application.get('student_name', '')}")
        if student is None:
            return self._reply(reply_token, "申請資料損壞，無法處理。")
        result = self.homework_booking_service.cancel_booking_by_approval(
            student=student,
            booking_key=str(application.get("booking_key") or ""),
        )
        if result.status != "success" or result.booking is None:
            self.queue_manager.db.mark_homework_cancel_application_invalid(
                application_id,
                reviewed_by=user_id,
                review_reason="預約已不存在或資料已變更，無法核准取消。",
            )
            self.notifier.push(
                str(application.get("student_user_id") or ""),
                "你的 Homework 逾期取消申請已失效：預約資料已不存在或已變更。",
            )
            return self._reply(reply_token, "這筆申請已標記失效：預約資料已不存在或已變更。")
        approved = self.queue_manager.db.approve_homework_cancel_application(application_id, user_id)
        self.notifier.push_flex(
            str(application.get("student_user_id") or ""),
            build_homework_cancel_application_result_flex(application=approved or application, approved=True),
        )
        return self._reply(reply_token, "已核准這筆逾期取消申請。")

    def _capture_homework_cancel_apply_review_reject(self, user_id: str, text: str, reply_token: str) -> list:
        application_id = self._parse_application_id(text, "homework:cancel:apply:review:reject:")
        if application_id is None:
            return self._reply(reply_token, "找不到指定的申請資料。")
        application = self.queue_manager.db.get_homework_cancel_application(application_id)
        if application is None or application.get("status") != "pending":
            return self._reply(reply_token, "這筆申請已經處理過或不存在。")
        if not self._is_homework_cancel_reviewer(user_id, application):
            return self._reply(reply_token, "你不是這筆申請的審核對象。")
        self._set_pending_state(
            user_id,
            "homework",
            {
                "type": "homework_cancel_review_reject_reason",
                "application_id": application_id,
            },
        )
        return self._reply(reply_token, "請輸入不許可理由。")

    def _capture_homework_cancel_apply_reject_reason(self, user_id: str, text: str, reply_token: str, state: dict) -> list:
        reason = str(text or "").strip()
        if not reason:
            return self._reply(reply_token, "不許可理由不可為空，請重新輸入。")
        application_id = int(state.get("application_id") or 0)
        application = self.queue_manager.db.get_homework_cancel_application(application_id)
        if application is None or application.get("status") != "pending":
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "這筆申請已經處理過或不存在。")
        if not self._is_homework_cancel_reviewer(user_id, application):
            self._clear_pending_state(user_id, "homework")
            return self._reply(reply_token, "你不是這筆申請的審核對象。")
        rejected = self.queue_manager.db.reject_homework_cancel_application(application_id, user_id, reason)
        self._clear_pending_state(user_id, "homework")
        if rejected is None:
            return self._reply(reply_token, "送出不許可結果失敗，請稍後再試。")
        self.notifier.push_flex(
            str(rejected.get("student_user_id") or ""),
            build_homework_cancel_application_result_flex(application=rejected, approved=False),
        )
        return self._reply(reply_token, "已送出不許可結果。")

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

    def _parse_application_id(self, text: str, prefix: str) -> int | None:
        if not text.startswith(prefix):
            return None
        try:
            application_id = int(text.removeprefix(prefix))
        except ValueError:
            return None
        return application_id if application_id > 0 else None

    def _is_homework_cancel_reviewer(self, user_id: str, application: dict) -> bool:
        target_user_id = str(
            self.homework_booking_service.config.ta_line_user_ids.get(str(application.get("sheet_name") or ""), "")
            or ""
        ).strip()
        return bool(target_user_id) and target_user_id == user_id
