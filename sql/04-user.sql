-- ============= --
-- Create Users  --
-- ============= --
CREATE USER assignmentAdmin IDENTIFIED WITH mysql_native_password BY 'assAdmin';
CREATE USER assignmentApp IDENTIFIED WITH mysql_native_password BY 'assApp';
CREATE USER assignmentRead IDENTIFIED WITH mysql_native_password BY 'assRead';

-- ====================== --
-- Apply User Privileges
-- ====================== --

GRANT ALL PRIVILEGES ON assignment.* TO assignmentAdmin@'%' WITH GRANT OPTION;
GRANT SUPER ON *.* TO assignmentAdmin@'%' WITH GRANT OPTION;
GRANT SELECT,INSERT,UPDATE,DELETE,EXECUTE,SHOW VIEW ON assignment.* TO assignmentApp@'%';
GRANT SELECT,SHOW VIEW,EXECUTE ON assignment.* TO assignmentRead@'%';
