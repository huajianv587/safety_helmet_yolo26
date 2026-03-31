create table if not exists public.persons (
    person_id text primary key,
    name text not null,
    employee_id text unique not null,
    department text not null,
    team text,
    role text,
    phone text,
    face_photo_url text,
    badge_photo_url text,
    status text not null default 'active',
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

alter table public.alerts add column if not exists person_id text references public.persons(person_id);
alter table public.alerts add column if not exists person_name text;
alter table public.alerts add column if not exists employee_id text;
alter table public.alerts add column if not exists team text;
alter table public.alerts add column if not exists role text;
alter table public.alerts add column if not exists phone text;
alter table public.alerts add column if not exists identity_status text not null default 'unresolved';
alter table public.alerts add column if not exists identity_source text;

drop trigger if exists trg_persons_updated_at on public.persons;
create trigger trg_persons_updated_at
before update on public.persons
for each row
execute function public.set_updated_at();
