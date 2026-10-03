import re

# --- Fix admin_handlers.py (Promotions) ---
with open("admin_handlers.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add get_tenant_id if not present
if "get_tenant_id" not in content:
    content = content.replace("from auth import require", "from auth import require, get_tenant_id")

# Fix list_promotions
content = re.sub(
    r"promos = list_promotions\(active_only=active_only\)",
    r"tenant_id = get_tenant_id(update.effective_user.id)\n    promos = list_promotions(active_only=active_only, tenant_id=tenant_id)",
    content
)

# Fix create_promotion
content = re.sub(
    r"promo_id, msg = create_promotion\(\n(.*?)product_id=product_id,\n(.*?)discount_type=discount_type,\n(.*?)discount_value=discount_value,\n(.*?)start_date=start_date,\n(.*?)end_date=end_date,\n(.*?)target_category=target_category\n(.*?)\)",
    r"tenant_id = get_tenant_id(update.effective_user.id)\n        promo_id, msg = create_promotion(\n\1product_id=product_id,\n\2discount_type=discount_type,\n\3discount_value=discount_value,\n\4start_date=start_date,\n\5end_date=end_date,\n\6target_category=target_category,\n            tenant_id=tenant_id\n\7)",
    content
)

# simpler approach for create_promotion if regex fails
if "tenant_id=tenant_id" not in content:
    # try replacing the call
    old_call = """promo_id, msg = create_promotion(
        product_id=product_id,
        discount_type=discount_type,
        discount_value=discount_value,
        start_date=start_date,
        end_date=end_date,
        target_category=target_category
    )"""
    new_call = """tenant_id = get_tenant_id(update.effective_user.id)
    promo_id, msg = create_promotion(
        product_id=product_id,
        discount_type=discount_type,
        discount_value=discount_value,
        start_date=start_date,
        end_date=end_date,
        target_category=target_category,
        tenant_id=tenant_id
    )"""
    content = content.replace(old_call, new_call)

with open("admin_handlers.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Updated admin_handlers.py")

# --- Fix admin_schedule_handlers.py ---
with open("admin_schedule_handlers.py", "r", encoding="utf-8") as f:
    content2 = f.read()

if "get_tenant_id" not in content2:
    content2 = content2.replace("from auth import require", "from auth import require, get_tenant_id")

# Fix list_schedules
content2 = re.sub(
    r"schedules = list_schedules\(active_only=active_only\)",
    r"tenant_id = get_tenant_id(update.effective_user.id)\n    schedules = list_schedules(active_only=active_only, tenant_id=tenant_id)",
    content2
)

# Fix create_schedule
old_sch_call = """schedule_id, msg = create_schedule(
        start_date=start_date,
        end_date=end_date,
        status=status,
        operating_hours=op_hours,
        reason=reason
    )"""
new_sch_call = """tenant_id = get_tenant_id(update.effective_user.id)
    schedule_id, msg = create_schedule(
        start_date=start_date,
        end_date=end_date,
        status=status,
        operating_hours=op_hours,
        reason=reason,
        tenant_id=tenant_id
    )"""
content2 = content2.replace(old_sch_call, new_sch_call)

with open("admin_schedule_handlers.py", "w", encoding="utf-8") as f:
    f.write(content2)

print("Updated admin_schedule_handlers.py")
