import tkinter as tk
from tkinter import ttk,messagebox
from .core import LabDB


class Form(tk.Toplevel):
    def __init__(self,parent,title,fields,save):
        super().__init__(parent);self.title(title);self.transient(parent);self.grab_set()
        frame=ttk.Frame(self,padding=18);frame.pack(fill='both',expand=True);variables={}
        for i,(key,title,value,options) in enumerate(fields):
            ttk.Label(frame,text=title).grid(row=i,column=0,padx=8,pady=6,sticky='w')
            var=tk.StringVar(value=str(value));variables[key]=var
            field=ttk.Combobox(frame,textvariable=var,values=options,state='readonly',width=42) if options else ttk.Entry(frame,textvariable=var,width=45)
            field.grid(row=i,column=1,sticky='ew',pady=6)
        def submit():
            try:save({k:v.get().strip() for k,v in variables.items()});self.destroy()
            except Exception as e:messagebox.showerror('입력 확인',str(e),parent=self)
        ttk.Button(frame,text='적용',command=submit).grid(row=len(fields),column=1,pady=12,sticky='e')


class Window(tk.Tk):
    def __init__(self,title,path=None):
        super().__init__();self.title(title);self.geometry('1150x780');self.minsize(950,650)
        self.db=LabDB(path)
        style=ttk.Style(self);style.theme_use('clam');style.configure('Treeview',rowheight=28,font=('맑은 고딕',10));style.configure('TLabel',font=('맑은 고딕',10));style.configure('TButton',font=('맑은 고딕',10),padding=6)
        self.root=ttk.Frame(self,padding=18);self.root.pack(fill='both',expand=True)
        ttk.Label(self.root,text=title,font=('맑은 고딕',21,'bold')).pack(anchor='w',pady=(0,10))
    def safe(self,action):
        try:return action()
        except Exception as e:messagebox.showerror('확인',str(e),parent=self)
    def table(self,parent,columns):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=8)
        tree=ttk.Treeview(frame,columns=columns,show='headings')
        for c in columns:tree.heading(c,text=c);tree.column(c,width=130,minwidth=65)
        scrollbar=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);scrollbar.pack(side='right',fill='y');tree.configure(yscrollcommand=scrollbar.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.pack(side='bottom',fill='x');tree.configure(xscrollcommand=horizontal.set)
        tree.pack(fill='both',expand=True);return tree
    def fill(self,tree,rows):
        selected=tree.selection();tree.delete(*tree.get_children())
        for key,row in rows:tree.insert('','end',iid=str(key),values=tuple('' if v is None else v for v in row))
        if selected and tree.exists(selected[0]):tree.selection_set(selected[0])
