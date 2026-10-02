-- entered_by is "on delete set null": removing a staff profile must not count as editing a
-- released result. The lock keeps covering the value, flag, range snapshot and version.
create or replace function private.prevent_released_result_edit()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  item_status public.lab_item_status;
begin
  select i.status into item_status from public.lab_order_items i where i.id = old.order_item_id;
  if item_status = 'released' and (
    row(new.order_item_id, new.parameter_id, new.value_numeric, new.value_text, new.flag,
        new.version, new.ref_low, new.ref_high, new.ref_critical_low, new.ref_critical_high,
        new.ref_text_normal, new.unit, new.parameter_name, new.entered_at)
    is distinct from
    row(old.order_item_id, old.parameter_id, old.value_numeric, old.value_text, old.flag,
        old.version, old.ref_low, old.ref_high, old.ref_critical_low, old.ref_critical_high,
        old.ref_text_normal, old.unit, old.parameter_name, old.entered_at)
    or (new.is_current and not old.is_current)
  ) then
    raise exception 'lab result % is released and cannot be changed', old.id
      using errcode = 'MF001';
  end if;
  return new;
end;
$$;
