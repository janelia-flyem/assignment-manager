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
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('protocol',''),1,'cell_type_validation','Cell type validation','Cell type validation');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'key','Key','Key');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('key',''),1,'body_id','Body ID','Body ID');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('key',''),1,'multibody','Multibody ID','Multiple Body IDs');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('key',''),1,'xyz','XYZ coords','XYZ coordinates');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('key',''),1,'body_xyz','Body/XYZ coords','Body/XYZ coordinates');

# INSERT INTO cv_term_relationship (is_current,type_id,subject_id,object_id) VALUES (1,getCvTermId('schema','associated_with',NULL),getCvTermId('protocol','orphan_link',NULL),getCvTermId('key','body_id',NULL));

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'project','Project','Project');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'filter','Filter','Task filter');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'roi','ROI','ROI');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'status','Status','Status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'size','Size','Size (number of voxels)');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'note','Note','Project note');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'group','Project group','Project group');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'source','Source','Source');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'neuroglancer_grayscale','Neuroglancer grayscale','Neuroglancer grayscale');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('project',''),1,'neuroglancer_segmentation','Neuroglancer segmentation','Neuroglancer segmentation');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'assignment','Assignment','Assignment');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('assignment',''),1,'note','Note','Assignment note');

INSERT INTO cv (version,is_current,name,display_name,definition) VALUES (1,1,'task','Task','Task');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'cluster_name','Cluster name','Cluster name');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'post','Postsynaptic','Postsynaptic');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'pre','Presynaptic','Presynaptic');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'status','Status','Status');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'note','Note','Task note');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'todo_type','Todo type','Todo type');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'todo_user','Todo user','Todo user');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'priority','Priority','Priority');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'coordinates','Coordinates','Point coordinates');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'task type','Task type','Task type');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'task result id','Task result ID','Task result ID');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'body ID A','Body ID A','Body ID A');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'body ID B','Body ID B','Body ID B');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'match_score','Match score','Match score');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'debug','Debug','Debugging JSON');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'dvid_result','DVID result','DVID result');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'dvid_user','DVID user','DVID user');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'supervoxel ID 1','Supervoxel ID 1','Supervoxel ID 1');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'supervoxel ID 2','Supervoxel ID 2','Supervoxel ID 2');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'supervoxel point 1','Supervoxel Point 1','Supervoxel Point 1');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'supervoxel point 2','Supervoxel Point 2','Supervoxel Point 2');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'body point 1','Body Point 1','Body Point 1');
INSERT INTO cv_term (cv_id,is_current,name,display_name,definition) VALUES (getCVId('task',''),1,'body point 2','Body Point 2','Body Point 2');


INSERT INTO user (name,first,last,janelia_id,email,organization) VALUES ('robsvi@gmail.com','Rob','Svirskas','svirskasr','svirskasr@hhmi.org','Software Solutions');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'super');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'admin');
INSERT INTO user_permission (user_id,permission) VALUES ((SELECT id FROM user WHERE janelia_id='svirskasr'),'FlyEM Proofreaders');
SET FOREIGN_KEY_CHECKS=1;
