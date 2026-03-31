create table if not exists public.person_face_profiles (
    profile_id uuid primary key default gen_random_uuid(),
    person_id text not null references public.persons(person_id) on delete cascade,
    source_name text not null,
    source_photo_url text,
    embedding_json jsonb not null,
    embedding_version text not null default 'facenet_pytorch_vggface2',
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_person_face_profiles_person_id
on public.person_face_profiles (person_id);

alter table public.alerts add column if not exists identity_confidence double precision;
alter table public.alerts add column if not exists badge_text text;
alter table public.alerts add column if not exists badge_confidence double precision;
alter table public.alerts add column if not exists face_match_score double precision;
alter table public.alerts add column if not exists face_crop_path text;
alter table public.alerts add column if not exists face_crop_url text;
alter table public.alerts add column if not exists badge_crop_path text;
alter table public.alerts add column if not exists badge_crop_url text;
alter table public.alerts add column if not exists review_note text;
alter table public.alerts add column if not exists llm_provider text;
alter table public.alerts add column if not exists llm_summary text;

drop trigger if exists trg_person_face_profiles_updated_at on public.person_face_profiles;
create trigger trg_person_face_profiles_updated_at
before update on public.person_face_profiles
for each row
execute function public.set_updated_at();
