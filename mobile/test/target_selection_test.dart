import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:yu_coach/data/analysis_server_client.dart';
import 'package:yu_coach/pages/target_selection_page.dart';

void main() {
  testWidgets(
    'select exact image coordinates, confirm range, keep anchor on browsing',
    (tester) async {
      tester.view.physicalSize = const Size(480, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final imageBytes = await tester.runAsync(() async {
        final sample = File(
          '../output/target_lock_verification/source_000000.jpg',
        );
        if (sample.existsSync()) return sample.readAsBytes();
        final recorder = ui.PictureRecorder();
        Canvas(recorder).drawRect(
          const Rect.fromLTWH(0, 0, 960, 540),
          Paint()..color = Colors.blueGrey,
        );
        final picture = recorder.endRecording();
        final image = await picture.toImage(960, 540);
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        image.dispose();
        picture.dispose();
        return data!.buffer.asUint8List();
      });
      final font = File('C:/Windows/Fonts/msyh.ttc');
      if (font.existsSync()) {
        await tester.runAsync(() async {
          final loader = FontLoader('SelectionTest');
          loader.addFont(
            Future.value(ByteData.sublistView(await font.readAsBytes())),
          );
          await loader.load();
        });
      }
      final requested = <int>[];
      final client = AnalysisServerClient(
        client: MockClient((req) async {
          if (req.url.path.endsWith('metadata')) {
            return http.Response(
              jsonEncode({
                'fps': 240,
                'frame_count': 144,
                'width': 960,
                'height': 540,
                'frame_interval_ms': 1000 / 240,
              }),
              200,
            );
          }
          requested.add(int.parse(req.url.pathSegments.last));
          return http.Response.bytes(imageBytes!, 200);
        }),
      );
      addTearDown(client.close);
      Map<String, dynamic>? selected;
      final capture = GlobalKey();
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(fontFamily: 'SelectionTest'),
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () async {
                  selected = await Navigator.push<Map<String, dynamic>>(
                    context,
                    MaterialPageRoute(
                      builder: (_) => RepaintBoundary(
                        key: capture,
                        child: TargetSelectionPage(
                          client: client,
                          baseUrl: 'http://localhost',
                          videoId: 'id',
                        ),
                      ),
                    ),
                  );
                },
                child: const Text('open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '确认人物和区间'))
            .onPressed,
        isNull,
      );
      final bounds = tester.getRect(find.byKey(const Key('target-canvas')));
      // Draw around the runner in the actual 16:9 image, no letterbox coordinates.
      final from = Offset(
        bounds.left + bounds.width * .265,
        bounds.top + bounds.height * .478,
      );
      final to = Offset(
        bounds.left + bounds.width * .395,
        bounds.top + bounds.height * .600,
      );
      final gesture = await tester.startGesture(from);
      await gesture.moveTo(
        Offset((from.dx + to.dx) / 2, (from.dy + to.dy) / 2),
      );
      await tester.pump();
      await gesture.moveTo(to);
      await gesture.up();
      await tester.pumpAndSettle();
      expect(find.textContaining('选人起始帧：0'), findsOneWidget);
      await tester.ensureVisible(find.text('+10 帧'));
      await tester.tap(find.text('+10 帧'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('将当前帧设为结束帧'));
      await tester.tap(find.text('将当前帧设为结束帧'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byType(CheckboxListTile));
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('返回选人帧核对'));
      await tester.tap(find.text('返回选人帧核对'));
      await tester.pumpAndSettle();
      expect(requested, [0, 10, 0]);
      await tester.runAsync(
        () => precacheImage(
          tester.widget<Image>(find.byType(Image).first).image,
          tester.element(find.byType(Image).first),
        ),
      );
      await tester.pumpAndSettle();
      await tester.runAsync(() async {
        final boundary =
            capture.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final image = await boundary.toImage();
        final png = await image.toByteData(format: ui.ImageByteFormat.png);
        final file = File(
          '../output/target_lock_verification/selection_page.png',
        );
        await file.parent.create(recursive: true);
        await file.writeAsBytes(png!.buffer.asUint8List());
        image.dispose();
      });
      await tester.ensureVisible(find.text('确认人物和区间'));
      await tester.tap(find.text('确认人物和区间'));
      await tester.pumpAndSettle();
      expect(selected!['frame'], 0);
      expect(selected!['end_frame'], 10);
      final box = selected!['bbox'] as List;
      for (var i = 0; i < 4; i++) {
        expect(box[i], closeTo([.265, .478, .395, .600][i], .002));
      }
      expect(selected!['confirmed'], isTrue);
    },
  );

  test('target selection passes unchanged to analysis', () async {
    final target = {
      'protocol': 'athlete_lock_v1',
      'frame': 0,
      'end_frame': 143,
      'bbox': [.1, .1, .3, .9],
      'confirmed': true,
    };
    final client = AnalysisServerClient(
      client: MockClient((req) async {
        expect(jsonDecode(req.body)['target_selection'], target);
        return http.Response('{"job_id":"job"}', 202);
      }),
    );
    addTearDown(client.close);
    await client.submitAnalysis(
      baseUrl: 'http://localhost',
      videoId: 'id',
      athleteId: 'at1',
      athleteName: 'test',
      targetSelection: target,
    );
  });
}
