SET FOREIGN_KEY_CHECKS=0;
TRUNCATE TABLE task_property;
TRUNCATE TABLE task;
TRUNCATE TABLE task_audit;
TRUNCATE TABLE assignment_property;
TRUNCATE TABLE assignment;
TRUNCATE TABLE project_property;
TRUNCATE TABLE project;
TRUNCATE TABLE cv_term_relationship;
TRUNCATE TABLE cv_term;
TRUNCATE TABLE cv;
TRUNCATE TABLE user;
TRUNCATE TABLE user_permission;

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'schema','relationships defined in the schema','relationships defined in the schema');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('schema',''),1,'associated_with',NULL,NULL);

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'disposition','Disposition','Disposition');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('disposition',''),1,'In progress','In progress','In progress (started)');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('disposition',''),1,'Complete','Complete','Complete');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('disposition',''),1,'Skipped','Skipped','Skipped');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'protocol','Project type','Project type');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'cleave','Cleave','Cleave');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'false_split_review','False split review','False split review - NeuPrint');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'focused_merge','Focused merge','Focused merge - NeuPrint');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'link_by_point','Link by point','Link by point - DVID');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'neuron_validation','Neuron validation','Neuron validation - NeuPrint');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'orphan_link','Orphan link','Orphan link - NeuPrint');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'synapse_review_body','Synapse review (body)','Synapse review (body) - NeuPrint');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'synapse_review_coordinate','Synapse review (coordinate)','Synapse review (coordinate) - NeuPrint');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'synapse_review_roi','Synapse review (ROI)','Synapse review (ROI) - [precomputed]');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'tip_detection','Tip detection','Tip detection - DVID');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'todo','To do','To do - DVID');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'connection_validation','Connection validation','Connection validation - NeuTu');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'key','Key','Key');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('key',''),1,'body_id','Body ID','Body ID');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('key',''),1,'xyz','XYZ coords','XYZ coordinates');

# INSERT INTO cv_term_relationship (is_current,type_id,subject_id,object_id) VALUES (1,getCvTermId('schema','associated_with',NULL),getCvTermId('protocol','orphan_link',NULL),getCvTermId('key','body_id',NULL));

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'project','Project','Project');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'filter','Filter','Task filter');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'roi','ROI','ROI');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'status','Status','Status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'size','Size','Size (number of voxels)');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'note','Note','Project note');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'group','Project group','Project group');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'source','Source','Source');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'assignment','Assignment','Assignment');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('assignment',''),1,'note','Note','Assignment note');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'task','Task','Task');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'cluster_name','Cluster name','Cluster name');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'post','Postsynaptic','Postsynaptic');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'pre','Presynaptic','Presynaptic');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'status','Status','Status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'note','Note','Task note');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'todo_type','Todo type','Todo type');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'priority','Priority','Priority');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'coordinates','Coordinates','Point coordinates');

INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('robsvi@gmail.com','Rob','Svirskas','svirskasr','svirskasr@hhmi.org','Software Solutions');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'cleave');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'orphan_link');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'super');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'admin');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'FlyEM Proofreaders');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'Connectome Annotation Team');
INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('olbris@gmail.com','Donald','Olbris','olbrisd','olbrisd@hhmi.org','Software Engineering');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='olbrisd'),'orphan_link');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='olbrisd'),'admin');
INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('erika.neace@gmail.com','Erika','Neace','neacee','neacee@hhmi.org','FlyEM Proofreaders');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'cleave');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'orphan_link');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'todo');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'admin');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'FlyEM Project and Software');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'FlyEM Proofreaders');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='neacee'),'Connectome Annotation Team');
INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('patrivlin@gmail.com','Pat','Rivlin','rivlinp','rivlinp@hhmi.org','FlyEM Project and Software');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'cleave');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'orphan_link');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'todo');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'admin');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'FlyEM Project and Software');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'FlyEM Proofreaders');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='rivlinp'),'Connectome Annotation Team');
SET FOREIGN_KEY_CHECKS=1;
