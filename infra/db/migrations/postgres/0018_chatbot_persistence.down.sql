-- Rollback 0018_chatbot_persistence: drop chatbot state tables (policies drop with the tables).
SET search_path TO public;

DROP TABLE IF EXISTS chatbot_scenarios;
DROP TABLE IF EXISTS chatbot_feedback;
DROP TABLE IF EXISTS chatbot_handoffs;
DROP TABLE IF EXISTS chatbot_sessions;
