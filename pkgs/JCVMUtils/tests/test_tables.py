from jcvmutils.tables import Table


def test_tables():
    class Result(Table):
        ''' Test class'''
        APP_DESCRIPTION = 'Script for creating HTML tables from different attack scenarios'
        ATTACK_NAME = 'Test Attack'
        STAGES = {}

    expected_doc = '''<!DOCTYPE html>
<html>
  <head>
    <title>Test Attack attack</title>
    <link href="../../../tables/stylesheet.css" rel="stylesheet">
  </head>
  <body>
    <body>
      <table>
        <tbody>
          <caption>Test Attack</caption>
          <tr>
            <th>card-name</th>
            <th>installation</th>
            <th>uninstallation</th>
          </tr>
        </tbody>
      </table>
    </body>
  </body>
</html>'''

    res = Result()
    doc = res.run()
    assert doc == expected_doc