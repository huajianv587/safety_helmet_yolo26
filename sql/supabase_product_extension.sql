alter table public.cameras add column if not exists enabled boolean not null default true;
alter table public.cameras add column if not exists site_name text;
alter table public.cameras add column if not exists building_name text;
alter table public.cameras add column if not exists floor_name text;
alter table public.cameras add column if not exists workshop_name text;
alter table public.cameras add column if not exists zone_name text;
alter table public.cameras add column if not exists responsible_department text;
alter table public.cameras add column if not exists alert_emails jsonb not null default '[]'::jsonb;
alter table public.cameras add column if not exists retry_count integer not null default 0;
alter table public.cameras add column if not exists reconnect_count integer not null default 0;
alter table public.cameras add column if not exists last_error text;
alter table public.cameras add column if not exists last_frame_at timestamptz;
alter table public.cameras add column if not exists last_fps double precision;

alter table public.alerts add column if not exists event_no text;
alter table public.alerts add column if not exists clip_path text;
alter table public.alerts add column if not exists clip_url text;
alter table public.alerts add column if not exists assigned_to text;
alter table public.alerts add column if not exists assigned_email text;
alter table public.alerts add column if not exists handled_by text;
alter table public.alerts add column if not exists handled_at timestamptz;
alter table public.alerts add column if not exists resolution_note text;
alter table public.alerts add column if not exists remediation_snapshot_path text;
alter table public.alerts add column if not exists remediation_snapshot_url text;
alter table public.alerts add column if not exists false_positive boolean not null default false;
alter table public.alerts add column if not exists closed_at timestamptz;
alter table public.alerts add column if not exists alert_source text not null default 'model';
alter table public.alerts add column if not exists governance_note text;
alter table public.alerts add column if not exists track_id text;
alter table public.alerts add column if not exists site_name text;
alter table public.alerts add column if not exists building_name text;
alter table public.alerts add column if not exists floor_name text;
alter table public.alerts add column if not exists workshop_name text;
alter table public.alerts add column if not exists zone_name text;
alter table public.alerts add column if not exists responsible_department text;

create unique index if not exists idx_alerts_event_no on public.alerts (event_no);
create index if not exists idx_alerts_department on public.alerts (department);
create index if not exists idx_alerts_person_name on public.alerts (person_name);
create index if not exists idx_alerts_handled_at on public.alerts (handled_at desc);

create table if not exists public.alert_actions (
    action_id text primary key,
    alert_id text not null references public.alerts(alert_id) on delete cascade,
    event_no text,
    action_type text not null,
    actor text not null,
    actor_role text not null,
    note text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_alert_actions_alert_id on public.alert_actions (alert_id);
create index if not exists idx_alert_actions_created_at on public.alert_actions (created_at desc);

create table if not exists public.notification_logs (
    notification_id text primary key,
    alert_id text not null references public.alerts(alert_id) on delete cascade,
    event_no text,
    channel text not null,
    recipient text not null,
    subject text not null,
    status text not null,
    error_message text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_notification_logs_alert_id on public.notification_logs (alert_id);
create index if not exists idx_notification_logs_created_at on public.notification_logs (created_at desc);

create table if not exists public.hard_cases (
    case_id text primary key,
    alert_id text not null references public.alerts(alert_id) on delete cascade,
    event_no text,
    case_type text not null,
    snapshot_path text,
    snapshot_url text,
    clip_path text,
    clip_url text,
    note text,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_hard_cases_alert_id on public.hard_cases (alert_id);
create index if not exists idx_hard_cases_created_at on public.hard_cases (created_at desc);

create table if not exists public.audit_logs (
    audit_id text primary key,
    entity_type text not null,
    entity_id text not null,
    action_type text not null,
    actor text not null,
    actor_role text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_audit_logs_entity on public.audit_logs (entity_type, entity_id);
create index if not exists idx_audit_logs_created_at on public.audit_logs (created_at desc);
