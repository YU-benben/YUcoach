import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:yu_coach/data/analysis_server_client.dart';
import 'package:yu_coach/pages/manual_contact_review_page.dart';

void main() {
  testWidgets('review exact frames, mark both feet, confirm and submit', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(480, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final framePng = await tester.runAsync(() async {
      final recorder = ui.PictureRecorder();
      final canvas = Canvas(recorder);
      canvas.drawRect(
        const Rect.fromLTWH(0, 0, 320, 180),
        Paint()..color = Colors.blueGrey,
      );
      final picture = recorder.endRecording();
      final image = await picture.toImage(320, 180);
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      picture.dispose();
      return png!.buffer.asUint8List();
    });
    final fontFile = File('C:/Windows/Fonts/msyh.ttc');
    if (fontFile.existsSync()) {
      await tester.runAsync(() async {
        final loader = FontLoader('ReviewTest');
        loader.addFont(
          Future.value(ByteData.sublistView(await fontFile.readAsBytes())),
        );
        await loader.load();
      });
    }
    final frames = <int>[];
    Map<String, dynamic>? submitted;
    final client = AnalysisServerClient(
      client: MockClient((request) async {
        if (request.url.path.endsWith('metadata')) {
          return http.Response(
            jsonEncode({
              'fps': 240,
              'frame_count': 144,
              'frame_interval_ms': 1000 / 240,
            }),
            200,
          );
        }
        frames.add(int.parse(request.url.pathSegments.last));
        return http.Response.bytes(framePng!, 200);
      }),
    );
    addTearDown(client.close);
    final capture = GlobalKey();
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(fontFamily: 'ReviewTest'),
        home: Builder(
          builder: (context) {
            return Scaffold(
              body: TextButton(
                onPressed: () async {
                  submitted = await Navigator.push<Map<String, dynamic>>(
                    context,
                    MaterialPageRoute(
                      builder: (_) => RepaintBoundary(
                        key: capture,
                        child: ManualContactReviewPage(
                          client: client,
                          baseUrl: 'http://localhost',
                          videoId: 'video',
                        ),
                      ),
                    ),
                  );
                },
                child: const Text('open'),
              ),
            );
          },
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(frames, [0]);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, '确认标注并计算'))
          .onPressed,
      isNull,
    );
    await tester.tap(find.text('标记着地'));
    await tester.tap(find.text('+10 帧'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('标记离地'));
    await tester.tap(find.text('+10 帧'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButton<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('运动员右脚').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('标记着地'));
    await tester.tap(find.text('+10 帧'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('标记离地'));
    await tester.pumpAndSettle();
    for (var i = 0; i < 4; i++) {
      await tester.ensureVisible(find.byType(CheckboxListTile).at(i));
      await tester.tap(find.byType(CheckboxListTile).at(i));
      await tester.pumpAndSettle();
    }
    expect(frames, [0, 10, 20, 30]);
    // Save a rendered page for visual inspection; this is not an accuracy test.
    await tester.runAsync(() async {
      final boundary =
          capture.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await boundary.toImage();
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      final file = File('../output/manual_timing_verification/review_page.png');
      await file.parent.create(recursive: true);
      await file.writeAsBytes(png!.buffer.asUint8List());
      image.dispose();
    });
    await tester.ensureVisible(find.text('确认标注并计算'));
    await tester.tap(find.text('确认标注并计算'));
    await tester.pumpAndSettle();
    expect(submitted!['protocol'], 'manual_side_v1');
    expect((submitted!['events'] as List).map((e) => e['frame']), [
      0,
      10,
      20,
      30,
    ]);
    expect((submitted!['events'] as List).map((e) => e['side']), [
      'left',
      'left',
      'right',
      'right',
    ]);
  });

  test('manual annotations and protocol reach the server unchanged', () async {
    final review = {'protocol': 'manual_side_v1', 'events': <dynamic>[]};
    final client = AnalysisServerClient(
      client: MockClient((request) async {
        final payload = jsonDecode(request.body);
        expect(payload['analysis_mode'], 'manual_side_v1');
        expect(payload['manual_review'], review);
        return http.Response('{"job_id":"job"}', 202);
      }),
    );
    addTearDown(client.close);
    await client.submitAnalysis(
      baseUrl: 'http://localhost',
      videoId: 'video',
      athleteId: 'athlete',
      athleteName: 'test',
      manualReview: review,
    );
  });
}
