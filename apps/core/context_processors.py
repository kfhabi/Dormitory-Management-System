def navigation(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    name = user.email.split("@")[0]
    if user.role == "STUDENT":
        profile = getattr(user, "student_profile", None)
        if profile:
            name = profile.full_name
    return {"display_name": name, "is_manager": user.role in ("MANAGER", "ADMIN")}
