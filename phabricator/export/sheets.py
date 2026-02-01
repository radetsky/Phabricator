"""Google Sheets exporter for Phabricator reports."""

import os
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build


class GoogleSheetsExporter:
    """Export data to Google Sheets with charts."""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self, credentials_file: Optional[str] = None):
        """Initialize with service account credentials.

        Args:
            credentials_file: Path to service account JSON key file.
                            Falls back to GOOGLE_CREDENTIALS_FILE env var.
        """
        if not credentials_file:
            credentials_file = os.environ.get("GOOGLE_CREDENTIALS_FILE")

        if not credentials_file:
            raise ValueError(
                "Google credentials file not specified. "
                "Set GOOGLE_CREDENTIALS_FILE environment variable or pass credentials_file parameter."
            )

        if not os.path.exists(credentials_file):
            raise FileNotFoundError(f"Credentials file not found: {credentials_file}")

        self.credentials = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=self.SCOPES
        )
        self.sheets_service = build("sheets", "v4", credentials=self.credentials)
        self.drive_service = build("drive", "v3", credentials=self.credentials)

    def find_spreadsheet_by_name(self, name: str) -> Optional[str]:
        """Find a spreadsheet by name.

        Args:
            name: The name of the spreadsheet to find.

        Returns:
            The spreadsheet ID if found, None otherwise.
        """
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.spreadsheet'"
        results = (
            self.drive_service.files()
            .list(q=query, fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])
        if files:
            return files[0]["id"]
        return None

    def get_or_create_spreadsheet(self, title: str) -> str:
        """Get existing spreadsheet by name or create a new one.

        Args:
            title: The spreadsheet title to find or create.

        Returns:
            The spreadsheet ID.
        """
        spreadsheet_id = self.find_spreadsheet_by_name(title)
        if spreadsheet_id:
            print(f"Found existing spreadsheet: {title}")
            return spreadsheet_id
        print(f"Creating new spreadsheet: {title}")
        return self.create_spreadsheet(title)

    def create_spreadsheet(self, title: str) -> str:
        """Create a new spreadsheet.

        Args:
            title: Title for the new spreadsheet.

        Returns:
            The spreadsheet ID.
        """
        spreadsheet = {"properties": {"title": title}}
        result = (
            self.sheets_service.spreadsheets()
            .create(body=spreadsheet, fields="spreadsheetId")
            .execute()
        )
        return result.get("spreadsheetId")

    def get_spreadsheet_url(self, spreadsheet_id: str) -> str:
        """Get the URL for a spreadsheet."""
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    def _get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> Optional[int]:
        """Get the sheet ID for a named sheet."""
        spreadsheet = (
            self.sheets_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute()
        )
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
        return None

    def _add_sheet(self, spreadsheet_id: str, sheet_name: str) -> int:
        """Add a new sheet tab and return its ID."""
        request = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {"title": sheet_name}
                    }
                }
            ]
        }
        response = (
            self.sheets_service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body=request)
            .execute()
        )
        return response["replies"][0]["addSheet"]["properties"]["sheetId"]

    def export_data(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        headers: list[str],
        rows: list[list],
    ) -> int:
        """Write data to a sheet tab.

        Args:
            spreadsheet_id: The spreadsheet ID.
            sheet_name: Name for the sheet tab.
            headers: Column headers.
            rows: Data rows.

        Returns:
            The sheet ID.
        """
        sheet_id = self._get_sheet_id(spreadsheet_id, sheet_name)
        if sheet_id is None:
            sheet_id = self._add_sheet(spreadsheet_id, sheet_name)

        values = [headers] + rows
        body = {"values": values}

        range_name = f"'{sheet_name}'!A1"
        self.sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

        self._format_header_row(spreadsheet_id, sheet_id)

        return sheet_id

    def _format_header_row(self, spreadsheet_id: str, sheet_id: int):
        """Format the header row with bold text and frozen row."""
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {
                                "red": 0.9,
                                "green": 0.9,
                                "blue": 0.9,
                            },
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]
        self.sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def add_chart(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        chart_type: str,
        title: str,
        data_range: dict,
        options: Optional[dict] = None,
    ):
        """Add a chart to a sheet.

        Args:
            spreadsheet_id: The spreadsheet ID.
            sheet_id: The sheet ID where data is located.
            chart_type: Chart type (COLUMN, LINE, PIE, BAR).
            title: Chart title.
            data_range: Dict with startRowIndex, endRowIndex, startColumnIndex, endColumnIndex.
            options: Additional chart options.
        """
        options = options or {}

        chart_spec = {
            "title": title,
            "basicChart": {
                "chartType": chart_type,
                "legendPosition": "BOTTOM_LEGEND",
                "axis": [],
                "domains": [
                    {
                        "domain": {
                            "sourceRange": {
                                "sources": [
                                    {
                                        "sheetId": sheet_id,
                                        "startRowIndex": data_range.get("startRowIndex", 0),
                                        "endRowIndex": data_range.get("endRowIndex"),
                                        "startColumnIndex": 0,
                                        "endColumnIndex": 1,
                                    }
                                ]
                            }
                        }
                    }
                ],
                "series": [],
                "headerCount": 1,
            },
        }

        if chart_type == "PIE":
            del chart_spec["basicChart"]
            chart_spec["pieChart"] = {
                "legendPosition": "RIGHT_LEGEND",
                "domain": {
                    "sourceRange": {
                        "sources": [
                            {
                                "sheetId": sheet_id,
                                "startRowIndex": data_range.get("startRowIndex", 0),
                                "endRowIndex": data_range.get("endRowIndex"),
                                "startColumnIndex": 0,
                                "endColumnIndex": 1,
                            }
                        ]
                    }
                },
                "series": {
                    "sourceRange": {
                        "sources": [
                            {
                                "sheetId": sheet_id,
                                "startRowIndex": data_range.get("startRowIndex", 0),
                                "endRowIndex": data_range.get("endRowIndex"),
                                "startColumnIndex": options.get("valueColumn", 1),
                                "endColumnIndex": options.get("valueColumn", 1) + 1,
                            }
                        ]
                    }
                },
            }
        else:
            series_columns = options.get("seriesColumns", [1])
            for col in series_columns:
                chart_spec["basicChart"]["series"].append(
                    {
                        "series": {
                            "sourceRange": {
                                "sources": [
                                    {
                                        "sheetId": sheet_id,
                                        "startRowIndex": data_range.get("startRowIndex", 0),
                                        "endRowIndex": data_range.get("endRowIndex"),
                                        "startColumnIndex": col,
                                        "endColumnIndex": col + 1,
                                    }
                                ]
                            }
                        },
                        "targetAxis": "LEFT_AXIS",
                    }
                )

            if options.get("stacked"):
                chart_spec["basicChart"]["stackedType"] = "STACKED"

        anchor_row = options.get("anchorRow", data_range.get("endRowIndex", 10) + 2)
        anchor_col = options.get("anchorCol", 0)

        request = {
            "requests": [
                {
                    "addChart": {
                        "chart": {
                            "spec": chart_spec,
                            "position": {
                                "overlayPosition": {
                                    "anchorCell": {
                                        "sheetId": sheet_id,
                                        "rowIndex": anchor_row,
                                        "columnIndex": anchor_col,
                                    },
                                    "widthPixels": options.get("width", 600),
                                    "heightPixels": options.get("height", 400),
                                }
                            },
                        }
                    }
                }
            ]
        }

        self.sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=request
        ).execute()

    def export_task_report(
        self,
        tasks: list,
        title: str,
        spreadsheet_id: Optional[str] = None,
    ) -> str:
        """Export task report to Google Sheets.

        Args:
            tasks: List of formatted task dicts from TaskReporter.format_task().
            title: Spreadsheet title (used if creating new spreadsheet).
            spreadsheet_id: Optional existing spreadsheet ID.

        Returns:
            The spreadsheet ID.
        """
        if not spreadsheet_id:
            spreadsheet_id = self.get_or_create_spreadsheet(title)

        headers = [
            "ID",
            "Title",
            "Projects",
            "Status",
            "Priority",
            "Created",
            "Modified",
            "URL",
            "Author",
            "Owner",
        ]

        rows = []
        for task in tasks:
            projects = task.get("projects", [])
            if isinstance(projects, list):
                projects = ", ".join(projects)
            rows.append([
                task.get("id", ""),
                task.get("title", ""),
                projects,
                task.get("status", ""),
                task.get("priority", ""),
                str(task.get("created", "")),
                str(task.get("modified", "")),
                task.get("url", ""),
                task.get("author", ""),
                task.get("owner", ""),
            ])

        self.export_data(spreadsheet_id, "Tasks", headers, rows)

        print(f"Exported {len(tasks)} tasks to Google Sheets")
        print(f"URL: {self.get_spreadsheet_url(spreadsheet_id)}")

        return spreadsheet_id

    def export_lifecycle_report(
        self,
        durations: list[dict],
        title: str,
        spreadsheet_id: Optional[str] = None,
    ) -> str:
        """Export lifecycle report to Google Sheets with duration chart.

        Args:
            durations: List of duration dicts from LifecycleReporter.calculate_duration().
            title: Spreadsheet title (used if creating new spreadsheet).
            spreadsheet_id: Optional existing spreadsheet ID.

        Returns:
            The spreadsheet ID.
        """
        if not spreadsheet_id:
            spreadsheet_id = self.get_or_create_spreadsheet(title)

        headers = [
            "ID",
            "Title",
            "Status",
            "Priority",
            "Created",
            "Modified",
            "Closed",
            "URL",
            "Author",
            "Owner",
            "Duration (days)",
            "Duration (hours)",
        ]

        rows = []
        for d in durations:
            rows.append([
                d.get("task_id", ""),
                d.get("title", ""),
                d.get("status", ""),
                d.get("priority", ""),
                str(d.get("created_date", "")),
                str(d.get("modified_date", "")),
                str(d.get("closed_date", "")),
                d.get("url", ""),
                d.get("author", ""),
                d.get("owner", ""),
                d.get("duration_days", 0),
                d.get("duration_hours", 0),
            ])

        sheet_id = self.export_data(spreadsheet_id, "Lifecycle", headers, rows)

        if len(rows) > 1:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "BAR",
                "Task Duration (Days)",
                {
                    "startRowIndex": 0,
                    "endRowIndex": min(len(rows) + 1, 21),
                    "startColumnIndex": 0,
                    "endColumnIndex": 12,
                },
                {"seriesColumns": [10]},
            )

        print(f"Exported {len(durations)} lifecycle records to Google Sheets")
        print(f"URL: {self.get_spreadsheet_url(spreadsheet_id)}")

        return spreadsheet_id

    def export_stats_report(
        self,
        stats_data: dict,
        title: str,
        spreadsheet_id: Optional[str] = None,
    ) -> str:
        """Export stats report to Google Sheets with charts.

        Args:
            stats_data: Dict containing different stat types:
                - team_stats: List of team member stats
                - team_stats_periodic: Periodic team stats data
                - duration_by_member: Duration stats by member
                - duration_by_member_periodic: Periodic duration stats
                - duration_by_project: Duration stats by project
                - duration_by_project_periodic: Periodic duration stats by project
                - utilization: Utilization rate stats
                - utilization_periodic: Periodic utilization stats
            title: Spreadsheet title (used if creating new spreadsheet).
            spreadsheet_id: Optional existing spreadsheet ID.

        Returns:
            The spreadsheet ID.
        """
        if not spreadsheet_id:
            spreadsheet_id = self.get_or_create_spreadsheet(title)

        chart_anchor_row = 2

        if "team_stats" in stats_data:
            chart_anchor_row = self._export_team_stats(
                spreadsheet_id, stats_data["team_stats"]
            )

        if "team_stats_periodic" in stats_data:
            chart_anchor_row = self._export_team_stats_periodic(
                spreadsheet_id, stats_data["team_stats_periodic"]
            )

        if "duration_by_member" in stats_data:
            self._export_duration_by_member(
                spreadsheet_id, stats_data["duration_by_member"]
            )

        if "duration_by_member_periodic" in stats_data:
            self._export_duration_periodic(
                spreadsheet_id,
                stats_data["duration_by_member_periodic"],
                "Duration by Member",
                "member",
            )

        if "duration_by_project" in stats_data:
            self._export_duration_by_project(
                spreadsheet_id, stats_data["duration_by_project"]
            )

        if "duration_by_project_periodic" in stats_data:
            self._export_duration_periodic(
                spreadsheet_id,
                stats_data["duration_by_project_periodic"],
                "Duration by Project",
                "project",
            )

        if "utilization" in stats_data:
            self._export_utilization(spreadsheet_id, stats_data["utilization"])

        if "utilization_periodic" in stats_data:
            self._export_utilization_periodic(
                spreadsheet_id, stats_data["utilization_periodic"]
            )

        print(f"Exported stats report to Google Sheets")
        print(f"URL: {self.get_spreadsheet_url(spreadsheet_id)}")

        return spreadsheet_id

    def _export_team_stats(self, spreadsheet_id: str, stats: list[dict]) -> int:
        """Export non-periodic team stats."""
        headers = [
            "Member",
            "Resolved (Period)",
            "Open",
            "Authored (Period)",
            "Owned (Period)",
            "Resolved (Total)",
            "Authored (Total)",
            "Owned (Total)",
        ]

        rows = []
        for s in stats:
            rows.append([
                s.get("username", ""),
                s.get("resolved_in_period", 0),
                s.get("open_tasks", 0),
                s.get("authored_in_period", 0),
                s.get("owned_in_period", 0),
                s.get("resolved_total", 0),
                s.get("authored_total", 0),
                s.get("owned_total", 0),
            ])

        sheet_id = self.export_data(spreadsheet_id, "Team Stats", headers, rows)

        if rows:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "COLUMN",
                "Team Performance",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(rows) + 1,
                },
                {"seriesColumns": [1, 2, 3], "stacked": False},
            )

        return len(rows) + 20

    def _export_team_stats_periodic(self, spreadsheet_id: str, data: dict) -> int:
        """Export periodic team stats with time trends chart."""
        periods = data.get("periods", [])
        rows_data = data.get("rows", [])
        totals = data.get("totals", {})

        headers = ["Member"] + periods + ["Total"]

        rows = []
        for row in rows_data:
            resolved = row.get("resolved", [])
            total = sum(resolved)
            rows.append([row.get("member", "")] + resolved + [total])

        total_row = ["TOTAL"] + totals.get("resolved", []) + [sum(totals.get("resolved", []))]
        rows.append(total_row)

        sheet_id = self.export_data(spreadsheet_id, "Team Stats", headers, rows)

        if len(rows) > 1 and len(periods) > 1:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "COLUMN",
                "Team Performance by Period",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(rows),
                },
                {"seriesColumns": list(range(1, len(periods) + 1)), "stacked": True},
            )

            trend_headers = ["Period", "Total Resolved"]
            trend_rows = [[periods[i], totals.get("resolved", [])[i]] for i in range(len(periods))]

            trend_sheet_id = self.export_data(
                spreadsheet_id, "Time Trends", trend_headers, trend_rows
            )

            self.add_chart(
                spreadsheet_id,
                trend_sheet_id,
                "LINE",
                "Resolution Trends Over Time",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(trend_rows) + 1,
                },
                {"seriesColumns": [1]},
            )

        return len(rows) + 20

    def _export_duration_by_member(self, spreadsheet_id: str, stats: list[dict]):
        """Export duration by member stats."""
        headers = [
            "Member",
            "Tasks",
            "Avg Duration (Days)",
            "Avg Duration (Hours)",
            "Min Duration (Hours)",
            "Max Duration (Hours)",
        ]

        rows = []
        for s in stats:
            rows.append([
                s.get("username", ""),
                s.get("tasks_count", 0),
                s.get("avg_duration_days", 0),
                s.get("avg_duration_hours", 0),
                s.get("min_duration_hours", 0),
                s.get("max_duration_hours", 0),
            ])

        sheet_id = self.export_data(spreadsheet_id, "Duration by Member", headers, rows)

        if rows:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "BAR",
                "Average Duration by Team Member (Days)",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(rows) + 1,
                },
                {"seriesColumns": [2]},
            )

    def _export_duration_by_project(self, spreadsheet_id: str, stats: list[dict]):
        """Export duration by project stats."""
        headers = [
            "Project",
            "Tasks",
            "Avg Duration (Days)",
            "Avg Duration (Hours)",
            "Min Duration (Hours)",
            "Max Duration (Hours)",
        ]

        rows = []
        for s in stats:
            rows.append([
                s.get("project", ""),
                s.get("tasks_count", 0),
                s.get("avg_duration_days", 0),
                s.get("avg_duration_hours", 0),
                s.get("min_duration_hours", 0),
                s.get("max_duration_hours", 0),
            ])

        sheet_id = self.export_data(spreadsheet_id, "Duration by Project", headers, rows)

        if rows:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "BAR",
                "Average Duration by Project (Days)",
                {
                    "startRowIndex": 0,
                    "endRowIndex": min(len(rows) + 1, 16),
                },
                {"seriesColumns": [2]},
            )

    def _export_duration_periodic(
        self,
        spreadsheet_id: str,
        data: dict,
        sheet_name: str,
        row_label: str,
    ):
        """Export periodic duration data."""
        periods = data.get("periods", [])
        rows_data = data.get("rows", [])

        headers = [row_label.title()] + periods + ["Avg"]

        rows = []
        for row in rows_data:
            values = row.get("values", [])
            avg = row.get("avg", 0)
            rows.append([row.get(row_label, "")] + values + [avg])

        sheet_id = self.export_data(spreadsheet_id, sheet_name, headers, rows)

        if rows and len(periods) > 1:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "LINE",
                f"Duration Trends ({row_label.title()})",
                {
                    "startRowIndex": 0,
                    "endRowIndex": min(len(rows) + 1, 11),
                },
                {"seriesColumns": list(range(1, len(periods) + 1))},
            )

    def _export_utilization(self, spreadsheet_id: str, stats: list[dict]):
        """Export utilization rate stats with pie chart."""
        headers = [
            "Member",
            "Tasks",
            "Total Hours",
            "Task %",
            "Hours %",
        ]

        rows = []
        for s in stats:
            rows.append([
                s.get("username", ""),
                s.get("tasks_count", 0),
                s.get("total_hours", 0),
                s.get("task_percent", 0),
                s.get("hours_percent", 0),
            ])

        sheet_id = self.export_data(spreadsheet_id, "Utilization", headers, rows)

        if rows:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "PIE",
                "Workload Distribution (Tasks)",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(rows) + 1,
                },
                {"valueColumn": 1},
            )

            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "PIE",
                "Workload Distribution (Hours)",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(rows) + 1,
                },
                {"valueColumn": 2, "anchorCol": 8},
            )

    def _export_utilization_periodic(self, spreadsheet_id: str, data: dict):
        """Export periodic utilization data."""
        periods = data.get("periods", [])
        rows_data = data.get("rows", [])

        headers = ["Member"] + periods + ["Avg %"]

        rows = []
        for row in rows_data:
            values = row.get("values", [])
            avg = row.get("avg", 0)
            rows.append([row.get("member", "")] + values + [avg])

        sheet_id = self.export_data(spreadsheet_id, "Utilization", headers, rows)

        if rows and len(periods) > 1:
            self.add_chart(
                spreadsheet_id,
                sheet_id,
                "LINE",
                "Utilization Trends Over Time",
                {
                    "startRowIndex": 0,
                    "endRowIndex": len(rows) + 1,
                },
                {"seriesColumns": list(range(1, len(periods) + 1))},
            )
