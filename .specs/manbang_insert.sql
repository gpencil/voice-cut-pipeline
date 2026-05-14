-- 原始数据 2026-05-11

CREATE TABLE `manbang` (
   `id` bigint NOT NULL AUTO_INCREMENT,
   `m_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
   `voice_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
   PRIMARY KEY (`id`),
   UNIQUE KEY `idx_uid` (`m_id`) USING BTREE,
   UNIQUE KEY `idx_vid` (`voice_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=32 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (1, '4000000034976069146', 'manbang_1778327355914');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (2, '4000000013435071820', 'manbang_1778321797262');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (3, '4000000000003552500', 'manbang_1778321791359');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (4, '4000000031814291859', 'manbang_1778328544724');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (5, '4000000038189075384', 'manbang_1778329452745');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (6, '4000000051404100728', 'manbang_1778329660761');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (7, '4000000057855219994', 'manbang_1778329666100');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (8, '4000000049758282876', 'manbang_1778466711283');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (9, '4000000013773695386', 'manbang_1778467596390');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (10, '4000000066361908691', 'manbang_1778485751312');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (11, '96436390823225831', 'pencil_011');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (12, '96436391518148573', 'pencil_012');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (13, '600608457542544455', 'pencil_013');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (14, '23651742485884372', 'pencil_015');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (15, '4000000000000198433', 'pencil_014');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (16, '23651742483678266', 'pencil_009');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (17, '4000000000005402049', 'pencil_010');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (18, '4000000019211508511', 'pencil_007');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (19, '4000000021494776827', 'pencil_006');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (20, '600608457608523925', 'ipencill_005');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (21, '4000000000010709373', 'pencil_004');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (22, '4000000021719798280', 'pencil_003');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (23, '4000000025569054312', 'pencil_002');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (24, '96052842979356919', 'manbang_1778586610497');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (25, '4000000000002440969', 'manbang_1778588067052');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (29, '4000000020563728489', 'manbang_1778589042816');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (30, '4000000069968675018', 'manbang_1778589049127');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (32, '96315273746802420', 'manbang_1778589054726');
INSERT INTO `tts_dev`.`manbang` (`id`, `m_id`, `voice_id`) VALUES (33, '4000000035875721646', 'manbang_1778591289098');