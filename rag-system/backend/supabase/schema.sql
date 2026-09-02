-- schema.sql
--
-- Every user-data table has row_level_security ENABLED and a policy
-- that hard-restricts rows to `auth.uid() = user_id`. This is the
-- database-level backstop for multi-tenancy: even if a route handler
-- forgot a `.eq("user_id", ...)` filter, RLS still blocks the request
-- as long as it uses the user-scoped Supabase client (app/db.py's
-- get_user_client), not the service-role client.

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------------
-- documents
-- ---------------------------------------------------------------------
create table if not exists documents (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  source_name text not null,
  source_type text not null check (source_type in ('pdf','image','csv','youtube','docx')),
  uploaded_at timestamptz not null default now(),
  chunk_count int not null default 0,
  status text not null default 'processing' check (status in ('processing','ready','failed')),
  error_message text,
  -- Path of the original uploaded file inside the "documents" storage
  -- bucket, e.g. "{user_id}/{document_id}-{source_name}". Null for
  -- source types with no raw file to keep (youtube).
  storage_path text
);

alter table documents enable row level security;

create policy "documents_select_own" on documents
  for select using (auth.uid() = user_id);
create policy "documents_insert_own" on documents
  for insert with check (auth.uid() = user_id);
create policy "documents_update_own" on documents
  for update using (auth.uid() = user_id);
create policy "documents_delete_own" on documents
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- document_chunks
-- Lightweight text mirror of what's upserted into Pinecone, used only
-- to build the per-user BM25 corpus (Pinecone has no cheap "list all
-- vectors" API). Keeping this in Postgres also means BM25 corpus reads
-- go through the same RLS boundary as everything else.
-- ---------------------------------------------------------------------
create table if not exists document_chunks (
  chunk_id text primary key, -- "{document_id}::{chunk_index}"
  document_id uuid not null references documents(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  source_name text not null,
  chunk_index int not null,
  text text not null,
  created_at timestamptz not null default now()
);

alter table document_chunks enable row level security;

create policy "chunks_select_own" on document_chunks
  for select using (auth.uid() = user_id);
create policy "chunks_insert_own" on document_chunks
  for insert with check (auth.uid() = user_id);
create policy "chunks_delete_own" on document_chunks
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- chat_sessions
-- ---------------------------------------------------------------------
create table if not exists chat_sessions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  created_at timestamptz not null default now(),
  last_active_at timestamptz not null default now()
);

alter table chat_sessions enable row level security;

create policy "sessions_select_own" on chat_sessions
  for select using (auth.uid() = user_id);
create policy "sessions_insert_own" on chat_sessions
  for insert with check (auth.uid() = user_id);
create policy "sessions_update_own" on chat_sessions
  for update using (auth.uid() = user_id);
create policy "sessions_delete_own" on chat_sessions
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- chat_messages
-- ---------------------------------------------------------------------
create table if not exists chat_messages (
  id uuid primary key default uuid_generate_v4(),
  session_id uuid not null references chat_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  citations jsonb not null default '[]',
  confidence numeric,
  created_at timestamptz not null default now()
);

alter table chat_messages enable row level security;

create policy "messages_select_own" on chat_messages
  for select using (auth.uid() = user_id);
create policy "messages_insert_own" on chat_messages
  for insert with check (auth.uid() = user_id);
create policy "messages_delete_own" on chat_messages
  for delete using (auth.uid() = user_id);

create index if not exists idx_documents_user on documents(user_id);
create index if not exists idx_chunks_user on document_chunks(user_id);
create index if not exists idx_sessions_user on chat_sessions(user_id);
create index if not exists idx_messages_session on chat_messages(session_id);

-- ---------------------------------------------------------------------
-- Storage: "documents" bucket
--
-- Raw uploaded files (pdf/image/csv/docx) live here, one folder per
-- user: objects are stored at "{user_id}/{document_id}-{filename}".
-- That user_id folder prefix is what the RLS policies below check
-- against auth.uid(), so this gets the same "can't see another user's
-- files even via a raw storage query" guarantee that the Postgres
-- tables above get from their own RLS policies. Kept private (not
-- public) -- the frontend/backend always reach files via short-lived
-- signed URLs (see routers/documents.py), never a public bucket URL.
-- ---------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

create policy "storage_documents_select_own"
  on storage.objects for select
  using (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "storage_documents_insert_own"
  on storage.objects for insert
  with check (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "storage_documents_delete_own"
  on storage.objects for delete
  using (bucket_id = 'documents' and (storage.foldername(name))[1] = auth.uid()::text);

-- admin_schema.sql
--
-- Defines who's an admin via an explicit allowlist table rather than a
-- boolean column on auth.users (which Supabase manages and discourages
-- extending directly) or a client-editable "profiles.is_admin" flag
-- (which would need extremely careful RLS to stop a user granting
-- themselves admin). This table has NO insert/update/delete policy for
-- anon/authenticated roles at all -- the only way to add or remove an
-- admin is directly via the Supabase SQL editor (service role), or a
-- trusted backend script using the service-role key. The backend's
-- `get_current_admin` dependency (app/admin.py) also only ever reads
-- this table via the service-role client, never the per-user RLS
-- client, so there's no path where a normal user's client could even
-- attempt to read or write it.

create table if not exists admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade,
  added_at timestamptz not null default now()
);

alter table admin_users enable row level security;
-- Intentionally NO policies created: with RLS enabled and zero
-- policies, every role except the service-role key is denied by
-- default -- exactly the "only the backend, via service role, can
-- touch this" guarantee we want.

-- To make yourself the first admin, run this once (swap in your real
-- user id -- find it in Supabase Dashboard > Authentication > Users):
--
--   insert into admin_users (user_id)
--   values ('00000000-0000-0000-0000-000000000000');