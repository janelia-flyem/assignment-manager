CREATE OR REPLACE VIEW cv_relationship_vw AS
SELECT
    cv.id    AS context_id,
    cv.name  AS context,
    cv1.id   AS subject_id,
    cv1.name AS subject,
    cvt.id   AS relationship_id,
    cvt.name AS relationship,
    cv2.id   AS object_id,
    cv2.name AS object
FROM cv
   , cv_relationship cr
   , cv_term cvt
   , cv cv1
   , cv cv2
WHERE cr.type_id = cvt.id
  AND cr.subject_id = cv1.id
  AND cr.object_id = cv2.id
  AND cr.is_current = 1
  AND cvt.is_current = 1
  AND cv1.is_current = 1
  AND cv2.is_current = 1
  AND cv.id = cvt.cv_id
;

CREATE OR REPLACE VIEW cv_term_relationship_vw AS
SELECT
    cv_subject.id    AS subject_context_id,
    cv_subject.name  AS subject_context,
    cvt_subject.id   AS subject_id,
    cvt_subject.name AS subject,
    cv_rel.id        AS relationship_context_id,
    cv_rel.name      AS relationship_context,
    cvt_rel.id       AS relationship_id,
    cvt_rel.name     AS relationship,
    cv_object.id     AS object_context_id,
    cv_object.name   AS object_context,
    cvt_object.id    AS object_id,
    cvt_object.name  AS object
FROM cv_term_relationship cr
   , cv_term cvt_rel
   , cv cv_rel
   , cv_term cvt_subject
   , cv cv_subject
   , cv_term cvt_object
   , cv cv_object
WHERE cr.type_id = cvt_rel.id
  AND cv_rel.id = cvt_rel.cv_id
  AND cr.subject_id = cvt_subject.id
  AND cv_subject.id = cvt_subject.cv_id
  AND cr.object_id = cvt_object.id
  AND cv_object.id = cvt_object.cv_id
  AND cr.is_current = 1
  AND cvt_rel.is_current = 1
  AND cvt_subject.is_current = 1
  AND cvt_object.is_current = 1
;

CREATE OR REPLACE VIEW cv_term_to_table_mapping_vw AS
SELECT cv_subject.name AS cv
      ,subject.id      AS cv_term_id
      ,subject.name    AS cv_term
      ,type.name       AS relationship
      ,object.name     AS schema_term
FROM cv_term_relationship 
JOIN cv_term type ON (type.id = cv_term_relationship.type_id)
JOIN cv cv_type ON (cv_type.id = type.cv_id)
JOIN cv_term subject ON (subject.id = cv_term_relationship.subject_id)
JOIN cv cv_subject ON (cv_subject.id = subject.cv_id)
JOIN cv_term object ON (object.id = cv_term_relationship.object_id)
WHERE cv_type.name = 'schema'
;

CREATE OR REPLACE VIEW cv_term_validation_vw AS
SELECT cv_subject.name AS term_context
      ,subject.id AS term_id
      ,subject.name AS term
      ,type.name AS relationship
      ,object.name AS rule
FROM cv_term_relationship 
JOIN cv_term type ON (type.id = cv_term_relationship.type_id)
JOIN cv_term subject ON (subject.id = cv_term_relationship.subject_id)
JOIN cv cv_subject ON (cv_subject.id = subject.cv_id)
JOIN cv_term object ON (object.id = cv_term_relationship.object_id)
JOIN cv cv_type ON (cv_type.id = type.cv_id)
WHERE type.name = 'validated_by'
;

CREATE OR REPLACE VIEW cv_term_vw AS
SELECT 
    cv.name          AS cv,
    cvt.id           AS id,
    cvt.name         AS cv_term,
    cvt.definition   AS definition,
    cvt.display_name AS display_name,
    cvt.data_type    AS data_type,
    cvt.is_current   AS is_current, 
    cvt.create_date  AS create_date
FROM cv
   , cv_term cvt
WHERE cv.id = cvt.cv_id
;

CREATE OR REPLACE VIEW project_vw AS
SELECT 
    p.id          AS id,
    p.name        AS name,
    ptype.name    AS protocol,
    p.roi         AS roi,
    p.status      AS status,
    p.disposition AS disposition,
    pp.value      AS note,
    p.create_date AS create_date
FROM project p
JOIN cv_term ptype ON (p.protocol_id = ptype.id)
JOIN cv ptype_cv ON (ptype.cv_id = ptype_cv.id AND ptype_cv.name = 'protocol')
LEFT OUTER JOIN project_property_vw pp ON (pp.project_id=p.id AND pp.type='note')
;

CREATE OR REPLACE VIEW project_property_vw AS
SELECT p.id          AS id
      ,pp.id           AS project_id
      ,p.name         AS name
      ,cv.name        AS cv
      ,cv_term.name   AS type
      ,pp.value       AS value
      ,pp.create_date AS create_date
FROM project_property pp
JOIN project p ON (pp.project_id = p.id)
JOIN cv_term ON (pp.type_id = cv_term.id)
JOIN cv ON (cv_term.cv_id = cv.id)
;

CREATE OR REPLACE VIEW assignment_vw AS
SELECT 
    a.id               AS id,
    a.name             AS name,
    p.name             AS project,
    p.protocol         AS protocol,
    ap.value           AS note,
    a.disposition      AS disposition,
    a.user             AS user,
    a.start_date       AS start_date,
    a.completion_date  AS completion_date,
    a.duration         AS duration,
    a.working_duration AS working_duration,
    a.create_date      AS create_date
FROM assignment a
JOIN project_vw p ON (p.id = a.project_id)
LEFT OUTER JOIN assignment_property_vw ap ON (ap.assignment_id=a.id AND ap.type='note')
;

CREATE OR REPLACE VIEW assignment_property_vw AS
SELECT ap.id          AS id
      ,a.id           AS assignment_id
      ,a.name         AS name
      ,cv.name        AS cv
      ,cv_term.name   AS type
      ,ap.value       AS value
      ,ap.create_date AS create_date
FROM assignment_property ap
JOIN assignment a ON (ap.assignment_id = a.id)
JOIN cv_term ON (ap.type_id = cv_term.id)
JOIN cv ON (cv_term.cv_id = cv.id)
;

CREATE OR REPLACE VIEW task_vw AS
SELECT 
    t.id              AS id,
    t.name            AS name,
    p.name            AS project,
    t.project_id      AS project_id,
    a.name            AS assignment,
    t.assignment_id   AS assignment_id,
    ktype.name        AS key_type,
    t.key_text        AS key_text,
    tp.value          AS note,
    t.disposition     AS disposition,
    t.user            AS user,
    t.start_date      AS start_date,
    t.completion_date AS completion_date,
    t.create_date     AS create_date
FROM task t
JOIN project p ON (p.id = t.project_id)
LEFT OUTER JOIN assignment a ON (a.id = t.assignment_id)
JOIN cv_term ktype ON (t.key_type_id = ktype.id)
JOIN cv ktype_cv ON (ktype.cv_id = ktype_cv.id AND ktype_cv.name = 'key')
LEFT OUTER JOIN task_property_vw tp ON (tp.task_id=t.id AND tp.type='note')
;

CREATE OR REPLACE VIEW task_property_vw AS
SELECT tp.id          AS id
      ,t.id           AS task_id
      ,t.name         AS name
      ,cv.name        AS cv
      ,cv_term.name   AS type
      ,tp.value       AS value
      ,tp.create_date AS create_date
FROM task_property tp
JOIN task t ON (tp.task_id = t.id)
JOIN cv_term ON (tp.type_id = cv_term.id)
JOIN cv ON (cv_term.cv_id = cv.id)
;
