-- pgvector: embeddings for the patient-record chatbot. Lives in `extensions`, never `public`.
create extension if not exists vector with schema extensions;
