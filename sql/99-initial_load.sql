SET FOREIGN_KEY_CHECKS=0;
TRUNCATE TABLE task_property;
TRUNCATE TABLE task;
TRUNCATE TABLE assignment_property;
TRUNCATE TABLE assignment;
TRUNCATE TABLE project_property;
TRUNCATE TABLE project;
TRUNCATE TABLE cv_term_relationship;
TRUNCATE TABLE cv_term;
TRUNCATE TABLE cv;

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
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'to_do','To do','To do - DVID');

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

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'assignment','Assignment','Assignment');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('assignment',''),1,'note','Note','Assignment note');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'task','Task','Task');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'cluster_name','Cluster name','Cluster name');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'post','Postsynaptic','Postsynaptic');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'pre','Presynaptic','Presynaptic');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'status','Status','Status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'note','Note','Task note');
SET FOREIGN_KEY_CHECKS=1;
