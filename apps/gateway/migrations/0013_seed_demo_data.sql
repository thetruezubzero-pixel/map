-- Demo seed data so a fresh install shows a populated map + working search
-- out of the box, instead of an empty shell. Without this, research_entities
-- is empty until the Airflow ingestion DAGs run (which aren't part of the
-- default `docker compose up`), so the map has no markers and search/chat
-- return nothing -- which reads as "the app does nothing."
--
-- These are real, public geographic facts (landmarks, transit hubs, cities)
-- plus a small set of well-known public companies at their real HQ
-- locations, and a few illustrative filing/news rows. Every row is tagged
-- with a source + license and flagged `"demo": true` in metadata so it's
-- clearly sample data, not something masquerading as a real ingested feed.
-- Safe to delete this migration (and `DELETE FROM research_entities WHERE
-- metadata->>'demo' = 'true'`) once real ingestion is wired.
--
-- geom is written lon/lat via ST_MakePoint(lon, lat); search_vector is
-- populated by the BEFORE INSERT trigger (0002), so these are immediately
-- searchable. ON CONFLICT keeps it idempotent against the
-- (source, entity_type, name) unique constraint (0004).

INSERT INTO research_entities (name, entity_type, source, license, geom, metadata) VALUES
-- Chicago-area landmarks / POIs (real coords, OpenStreetMap-style public data)
('Willis Tower', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6359, 41.8789), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Millennium Park', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6226, 41.8826), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Cloud Gate (The Bean)', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6233, 41.8827), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Navy Pier', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6086, 41.8917), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Art Institute of Chicago', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6237, 41.8796), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Field Museum', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6170, 41.8663), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Shedd Aquarium', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6140, 41.8676), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Wrigley Field', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6553, 41.9484), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Museum of Science and Industry', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.5831, 41.7906), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Lincoln Park Zoo', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6337, 41.9217), 4326), '{"demo": true, "city": "Chicago, IL"}'),
-- Chicago-area locations / transit / cities (incl. the Montgomery IL area you searched)
('O''Hare International Airport', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.9073, 41.9742), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Chicago Union Station', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-87.6398, 41.8786), 4326), '{"demo": true, "city": "Chicago, IL"}'),
('Montgomery, Illinois', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-88.3376, 41.7297), 4326), '{"demo": true, "county": "Kane/Kendall, IL"}'),
('Aurora, Illinois', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-88.3201, 41.7606), 4326), '{"demo": true, "county": "Kane, IL"}'),
('Naperville, Illinois', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-88.1535, 41.7508), 4326), '{"demo": true, "county": "DuPage, IL"}'),
-- Well-known public companies at their real Chicago-area HQ (sample business records)
('McDonald''s Corporation', 'business', 'sample_business', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6531, 41.8869), 4326), '{"demo": true, "hq": "Chicago, IL"}'),
('United Airlines Holdings', 'business', 'sample_business', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6359, 41.8789), 4326), '{"demo": true, "hq": "Chicago, IL (Willis Tower)"}'),
('Motorola Solutions', 'business', 'sample_business', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6412, 41.8807), 4326), '{"demo": true, "hq": "Chicago, IL"}'),
('Kraft Heinz Company', 'business', 'sample_business', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6354, 41.8885), 4326), '{"demo": true, "hq": "Chicago, IL"}'),
('Exelon Corporation', 'business', 'sample_business', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6366, 41.8858), 4326), '{"demo": true, "hq": "Chicago, IL"}'),
('Mondelez International', 'business', 'sample_business', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6377, 41.8880), 4326), '{"demo": true, "hq": "Chicago, IL"}'),
-- Illustrative public-filing rows (clearly sample, tied to the businesses above)
('McDonald''s Corp - SEC 10-K Annual Filing', 'government_filing', 'sample_sec', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6531, 41.8869), 4326), '{"demo": true, "form": "10-K", "note": "illustrative sample"}'),
('United Airlines - SEC 10-Q Quarterly Filing', 'government_filing', 'sample_sec', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6359, 41.8789), 4326), '{"demo": true, "form": "10-Q", "note": "illustrative sample"}'),
-- Illustrative news mentions (feed the news-density heatmap layer)
('Chicago tech sector expansion reported', 'news_mention', 'sample_news', 'sample/demo data', ST_SetSRID(ST_MakePoint(-87.6298, 41.8781), 4326), '{"demo": true, "note": "illustrative sample"}'),
('New commercial development approved in Aurora, IL', 'news_mention', 'sample_news', 'sample/demo data', ST_SetSRID(ST_MakePoint(-88.3201, 41.7606), 4326), '{"demo": true, "note": "illustrative sample"}'),
('Naperville business district revitalization', 'news_mention', 'sample_news', 'sample/demo data', ST_SetSRID(ST_MakePoint(-88.1535, 41.7508), 4326), '{"demo": true, "note": "illustrative sample"}'),
-- A few landmarks in other metros so the map is populated nationwide
('Statue of Liberty', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-74.0445, 40.6892), 4326), '{"demo": true, "city": "New York, NY"}'),
('Empire State Building', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-73.9857, 40.7484), 4326), '{"demo": true, "city": "New York, NY"}'),
('Central Park', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-73.9654, 40.7829), 4326), '{"demo": true, "city": "New York, NY"}'),
('Golden Gate Bridge', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-122.4783, 37.8199), 4326), '{"demo": true, "city": "San Francisco, CA"}'),
('Ferry Building', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-122.3937, 37.7955), 4326), '{"demo": true, "city": "San Francisco, CA"}'),
('Texas State Capitol', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-97.7404, 30.2747), 4326), '{"demo": true, "city": "Austin, TX"}'),
('University of Texas at Austin', 'location', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-97.7341, 30.2849), 4326), '{"demo": true, "city": "Austin, TX"}'),
('Griffith Observatory', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-118.3004, 34.1184), 4326), '{"demo": true, "city": "Los Angeles, CA"}'),
('Space Needle', 'poi', 'openstreetmap', 'ODbL', ST_SetSRID(ST_MakePoint(-122.3493, 47.6205), 4326), '{"demo": true, "city": "Seattle, WA"}')
ON CONFLICT (source, entity_type, name) DO NOTHING;
