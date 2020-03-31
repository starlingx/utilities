CREATE DATABASE collect;
USE collect;
CREATE TABLE openid_users(id INT not null AUTO_INCREMENT, name VARCHAR(60), email VARCHAR(200), openid VARCHAR(200), PRIMARY KEY (id));
CREATE TABLE launchpads(id INT not null, title VARCHAR(200), PRIMARY KEY (id));
CREATE TABLE files(id INT not null AUTO_INCREMENT, name VARCHAR(60), user_id INT not null, launchpad_id INT not null, modified_date TIMESTAMP, PRIMARY KEY (id), file_size FLOAT NOT NULL,
FOREIGN KEY (user_id) REFERENCES openid_users(id) ON DELETE CASCADE,
FOREIGN KEY (launchpad_id) REFERENCES launchpads(id) ON DELETE CASCADE);