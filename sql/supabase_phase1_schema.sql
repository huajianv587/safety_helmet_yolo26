create extension if not exists pgcrypto;

create table if not exists public.cameras (
    camera_id text primary key,
    camera_name text not null,
    source text not null,
    location text not null,
    department text not null,
    last_status text not null default 'offline',
    last_seen_at timestamptz,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.alerts (
    alert_id text primary key,
    event_key text not null,
    camera_id text not null references public.cameras(camera_id) on delete cascade,
    camera_name text not null,
    location text not null,
    department text not null,
    violation_type text not null default 'no_helmet',
    risk_level text not null default 'high',
    confidence double precision not null,
    snapshot_path text not null,
    snapshot_url text,
    status text not null default 'new',
    bbox jsonb not null,
    model_name text not null,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_alerts_created_at on public.alerts (created_at desc);
create index if not exists idx_alerts_camera_id on public.alerts (camera_id);
create index if not exists idx_alerts_status on public.alerts (status);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists trg_cameras_updated_at on public.cameras;
create trigger trg_cameras_updated_at
before update on public.cameras
for each row
execute function public.set_updated_at();

