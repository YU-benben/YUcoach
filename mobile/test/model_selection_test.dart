import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:yu_coach/data/analysis_server_client.dart';

void main() {
  for (final estimator in ['yolo', 'rtm']) {
    test('$estimator selection is included in the analysis request', () async {
      late Map<String, dynamic> payload;
      final client = AnalysisServerClient(
        client: MockClient((request) async {
          payload = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{"job_id":"job"}', 202);
        }),
      );
      addTearDown(client.close);
      final job = await client.submitAnalysis(
        baseUrl: 'http://localhost:8770',
        videoId: 'video',
        athleteId: 'athlete',
        athleteName: '测试',
        username: 'tester',
        estimator: estimator,
        model: 'yolov8s-pose.pt',
        imgsz: 1280,
        rtmMode: 'balanced',
      );
      expect(job, 'job');
      expect(payload['estimator'], estimator);
      if (estimator == 'yolo') {
        expect(payload['model'], 'yolov8s-pose.pt');
        expect(payload['imgsz'], 1280);
        expect(payload.containsKey('rtm_mode'), isFalse);
      } else {
        expect(payload['rtm_mode'], 'balanced');
        expect(payload.containsKey('model'), isFalse);
        expect(payload.containsKey('imgsz'), isFalse);
      }
    });
  }
}
