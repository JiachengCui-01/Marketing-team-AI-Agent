import tempfile
import unittest
import zipfile
from pathlib import Path

import openpyxl

from marketing_agent import file_inputs


class ExcelKnowledgeExtractionTests(unittest.TestCase):
    def test_xlsx_is_chunked_by_sheet_and_disconnected_regions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "供应商流程.xlsx"
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "采购审批"
            sheet.append(["步骤", "负责人", "输出"])
            sheet.append(["询价", "采购", "报价单"])
            sheet.append(["复核", "财务", "成本确认"])
            sheet.append([])
            sheet.append(["补充说明"])
            sheet.append(["金额超过 5 万元需要总经理审批"])
            workbook.save(path)

            result = file_inputs.extract(path)

        self.assertEqual(result["kind"], "text")
        self.assertGreaterEqual(len(result["chunks"]), 2)
        self.assertTrue(all("工作表/Sheet: 采购审批" in c for c in result["chunks"]))
        table = next(c for c in result["chunks"] if "报价单" in c)
        note = next(c for c in result["chunks"] if "总经理审批" in c)
        self.assertIn("步骤 | 负责人 | 输出", table)
        self.assertNotEqual(table, note)

    def test_large_table_chunks_repeat_the_header(self) -> None:
        rows = [["SKU", "产品名称", "处理动作"]]
        rows.extend([[f"SKU-{i}", "大件家具" * 15, f"动作 {i}"] for i in range(80)])
        chunks = file_inputs._render_excel_region(
            "products.xlsx", "产品", rows, (0, 0, len(rows) - 1, 2)
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all("SKU | 产品名称 | 处理动作" in chunk for chunk in chunks))
        self.assertTrue(all(len(chunk) <= file_inputs.MAX_EXCEL_CHUNK_CHARS + 100 for chunk in chunks))

    def test_editable_flowchart_shapes_and_connections_are_preserved(self) -> None:
        drawing = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
                  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <xdr:twoCellAnchor><xdr:from><xdr:col>1</xdr:col><xdr:row>1</xdr:row></xdr:from>
            <xdr:sp><xdr:nvSpPr><xdr:cNvPr id="2" name="Start"/></xdr:nvSpPr>
              <xdr:txBody><a:p><a:r><a:t>提交申请</a:t></a:r></a:p></xdr:txBody></xdr:sp>
          </xdr:twoCellAnchor>
          <xdr:twoCellAnchor><xdr:from><xdr:col>1</xdr:col><xdr:row>5</xdr:row></xdr:from>
            <xdr:sp><xdr:nvSpPr><xdr:cNvPr id="3" name="Review"/></xdr:nvSpPr>
              <xdr:txBody><a:p><a:r><a:t>主管审批</a:t></a:r></a:p></xdr:txBody></xdr:sp>
            <xdr:cxnSp><xdr:nvCxnSpPr><xdr:cNvPr id="4" name="Connector"/></xdr:nvCxnSpPr>
              <xdr:spPr><a:xfrm/></xdr:spPr><a:stCxn id="2" idx="0"/><a:endCxn id="3" idx="0"/></xdr:cxnSp>
          </xdr:twoCellAnchor>
        </xdr:wsDr>"""
        workbook = """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheets><sheet name="审批流程" sheetId="1"/></sheets></workbook>"""
        rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rId1" Target="../drawings/drawing1.xml"/>
        </Relationships>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flow.xlsx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("xl/workbook.xml", workbook)
                archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", rels)
                archive.writestr("xl/drawings/drawing1.xml", drawing)
            chunks = file_inputs._extract_xlsx_diagrams(path)

        combined = "\n".join(chunks)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("工作表/Sheet: 审批流程", combined)
        self.assertIn("节点/Node 2: 提交申请", combined)
        self.assertIn("提交申请 -> 主管审批", combined)

    def test_smartart_nodes_and_relationships_are_preserved(self) -> None:
        data = """<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram"
                     xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <dgm:ptLst>
            <dgm:pt modelId="a"><dgm:t><a:p><a:r><a:t>创建订单</a:t></a:r></a:p></dgm:t></dgm:pt>
            <dgm:pt modelId="b"><dgm:t><a:p><a:r><a:t>财务审核</a:t></a:r></a:p></dgm:t></dgm:pt>
          </dgm:ptLst>
          <dgm:cxnLst><dgm:cxn modelId="c" srcId="a" destId="b"/></dgm:cxnLst>
        </dgm:dataModel>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smartart.xlsx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("xl/diagrams/data1.xml", data)
            chunks = file_inputs._extract_xlsx_diagrams(path)

        combined = "\n".join(chunks)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("节点/Node a: 创建订单", combined)
        self.assertIn("创建订单 -> 财务审核", combined)


if __name__ == "__main__":
    unittest.main()
