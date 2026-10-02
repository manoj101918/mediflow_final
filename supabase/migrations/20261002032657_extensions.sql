-- Extensions live in the `extensions` schema (never `public`) so they are not exposed via the API.
create schema if not exists extensions;

-- btree_gist: lets the appointments exclusion constraint mix uuid equality with range overlap.
create extension if not exists btree_gist with schema extensions;

-- pg_trgm: fuzzy patient-name matching for duplicate warnings and search.
create extension if not exists pg_trgm with schema extensions;
